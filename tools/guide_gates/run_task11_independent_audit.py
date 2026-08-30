#!/usr/bin/env python3
"""Run the mechanically independent Task 11 evidence audit."""

from __future__ import annotations

import argparse
import ast
import base64
from collections.abc import Callable, Collection
from difflib import SequenceMatcher
import fnmatch
from hashlib import sha1, sha256
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
import xml.etree.ElementTree as ElementTree
import zlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)

from app.guide.application.public_event_envelope import (
    project_frontend_product,
)
from app.guide.presentation.contracts import ProductCard


REPORT_SCHEMA = "guide-task11-independent-audit-v1"
MANIFEST_SCHEMA = "guide-task11-candidate-manifest-v1"
RUNTIME_IDENTITY_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-identity-v1\x00"
)
RUNTIME_CHALLENGE_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-challenge-v1\x00"
)
RUNTIME_REPORT_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-parent-report-v1\x00"
)
PLAN_REVISION_PATTERN = re.compile(
    r"^Plan revision:\s*(\S+)\s*$",
    re.MULTILINE,
)
TASK11_EPOCH_PATTERN = re.compile(
    r"^Task 11 evidence epoch:\s*repair-epoch-(\d+)\s*$",
    re.MULTILINE,
)
ZERO_API_SANDBOX_PROFILE = (
    "(version 1)"
    "(allow default)"
    "(deny network-outbound)"
    "(allow network-outbound (remote ip \"localhost:*\"))"
    "(allow network-inbound)"
)
PRODUCTION_MATRIX_FIXTURE_PATH = (
    "tests/fixtures/guide/intent/"
    "task11_production_path_matrix_v1.jsonl"
)
SEMANTIC_MATRIX_FIXTURE_PATH = (
    "tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl"
)
PRODUCTION_MATRIX_TOOL_PATH = (
    "tools/guide_gates/run_task11_production_path_matrix.py"
)
BOUNDED_BROWSER_TOOL_PATH = (
    "tools/guide_gates/run_mainline_contract_browser_audit.py"
)
FIXTURE_TURNS = (
    "fixture-explore-recommendation",
    "fixture-fit-recommendation",
    "fixture-fit-clarification",
    "fixture-product-knowledge",
    "fixture-comparison",
    "fixture-image-identity",
    "fixture-image-fit-recommendation",
    "fixture-multi-image-comparison",
)
FIXTURE_PRESENTATION_EXPECTATIONS = {
    "fixture-explore-recommendation": (
        "recommendation",
        "recommendation",
        "explore",
        2,
        False,
    ),
    "fixture-fit-recommendation": (
        "recommendation",
        "recommendation",
        "fit",
        1,
        False,
    ),
    "fixture-product-knowledge": (
        "product_knowledge",
        "product_knowledge",
        None,
        1,
        False,
    ),
    "fixture-comparison": (
        "comparison",
        "comparison",
        None,
        2,
        False,
    ),
    "fixture-image-identity": (
        "image_identity",
        "image_identity",
        None,
        1,
        True,
    ),
    "fixture-image-fit-recommendation": (
        "recommendation",
        "recommendation",
        "fit",
        1,
        True,
    ),
    "fixture-multi-image-comparison": (
        "comparison",
        "comparison",
        None,
        2,
        True,
    ),
}
MANIFEST_CATEGORIES = (
    "source_paths",
    "test_paths",
    "tool_paths",
    "plan_paths",
    "fixture_paths",
)
RECLASSIFICATION_REGRESSION_NODE = (
    "tests/guide/runtime/test_feedback_frontend.py::"
    "test_feedback_target_lookup_requires_terminal_visible_products"
)
RECLASSIFICATION_CONTROL_NODE = (
    "tests/guide/runtime/test_feedback_frontend.py::"
    "test_feedback_target_commits_only_after_verified_stream_eof"
)
RECLASSIFICATION_FOCUSED_MODULES = frozenset(
    {
        "tests/guide/runtime/test_feedback_frontend.py",
        "tests/guide/runtime/test_frontend_presentation_stream.py",
        "tests/guide/runtime/test_frontend_scope.py",
        "tests/guide/runtime/test_runtime_http.py",
        "tests/guide/tools/test_attempt_ledger.py",
        "tests/guide/tools/test_build_task11_readiness.py",
        "tests/guide/tools/test_run_mainline_contract_browser_audit.py",
        "tests/guide/tools/test_run_task11_independent_audit.py",
    }
)
RECLASSIFICATION_FOCUSED_TEST_COUNT = 530
RECLASSIFICATION_POST_EVIDENCE_NODES = frozenset(
    {
        (
            "tests/guide/runtime/test_frontend_presentation_stream.py::"
            "test_general_knowledge_citations_render_after_terminal_validation"
        ),
        (
            "tests/guide/runtime/test_frontend_scope.py::"
            "test_general_knowledge_citations_reuse_existing_surface_"
            "without_empty_panel"
        ),
        (
            "tests/guide/runtime/test_frontend_scope.py::"
            "test_general_knowledge_payload_validator_enforces_citation_"
            "and_coverage_contract"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_consultation_turn_rejects_general_knowledge_event"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_demo_cli_dispatches_existing_bounded_browser_runner"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_demo_contract_allows_copywriter_fallback"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_demo_trajectories_cover_seven_modes_and_twenty_one_turns"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_demo_usefulness_accepts_fact_backed_generic_comparison"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_demo_usefulness_accepts_precise_product_evidence_gap"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_demo_usefulness_defers_typed_clarification_validation"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_demo_usefulness_rejects_all_unknown_generic_comparison"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_demo_usefulness_rejects_empty_product_knowledge"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_demo_usefulness_rejects_recommendation_without_fact_reason"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_demo_usefulness_rejects_ungrounded_product_knowledge"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_cli_requires_runtime_identity_and_manifest_hash"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_general_knowledge_cli_dispatches_existing_bounded_"
            "browser_runner"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_general_knowledge_trajectories_cover_six_observed_probes"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_general_knowledge_turn_accepts_bound_citations_and_gap"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_general_knowledge_turn_rejects_unusable_evidence"
            "[coverage-knowledge coverage mismatch]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_general_knowledge_turn_rejects_unusable_evidence"
            "[duplicate_id-duplicate knowledge citation]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_general_knowledge_turn_rejects_unusable_evidence"
            "[missing_panel-knowledge citation panel]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_general_knowledge_turn_rejects_unusable_evidence"
            "[missing_section-expected knowledge section]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_general_knowledge_turn_rejects_unusable_evidence"
            "[missing_source-expected knowledge source]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_general_knowledge_turn_rejects_unusable_evidence"
            "[no_public_answer-useful general knowledge answer]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_general_knowledge_turn_rejects_unusable_evidence"
            "[unlisted_source-unlisted knowledge source]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_general_knowledge_turn_rejects_unusable_evidence"
            "[unsupported_compatibility-compatibility gap]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_section_block_allows_required_fact_text_in_product_metadata"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_authorization_receipt_interruption_recovers_"
            "without_duplicate"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_authorization_receipt_survives_attempt_allocation"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_foreign_context_cannot_replace_rollback_witness"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_repository_context_survives_dual_sidecar_deletion"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_allocation_recovers_process_exit_before_ledger_commit"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_allocation_recovers_process_exit_after_ledger_commit"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_authorization_receipt_recovers_partial_final_write"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_checkpoint_authority_recovers_partial_final_write"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_allocation_requires_authorization_receipt"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_authorization_receipt_verifier_requires_complete_history"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_checkpoint_backfills_legacy_authorization_receipts"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_failed_attempt_can_bind_evidence_subdirectory"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_attempt_completed_can_rebind_evidence_directory"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_reclassify_accepts_indexed_runner_startup_evidence"
        ),
        (
            "tests/guide/tools/test_run_bound_runtime.py::"
            "test_runtime_shell_assets_do_not_take_business_authority_lease"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_runtime_request_authority_does_not_reverify_"
            "complete_readiness"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_version_sync_timeout_reclassification_uses_"
            "runtime_gate_owner"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_authorization_validates_repair_before_exclusive_"
            "ledger_lock"
        ),
        (
            "tests/guide/tools/test_run_bound_runtime.py::"
            "test_runtime_releases_ledger_lock_before_entering_application"
        ),
        (
            "tests/guide/tools/test_run_bound_runtime.py::"
            "test_runtime_version_check_uses_lightweight_authority_check"
        ),
        (
            "tests/guide/tools/test_run_bound_runtime.py::"
            "test_bound_runtime_has_no_parallel_consumed_check"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_attempt_10_reclassification_derives_runtime_gate_owner"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_attempt_11_reclassification_derives_version_sync_owner"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_runtime_request_authority_repair_rejects_unbound_files"
        ),
        (
            "tests/guide/tools/test_single_path_architecture.py::"
            "test_processor_cannot_delegate_through_local_callable_alias"
        ),
        (
            "tests/guide/tools/test_single_path_architecture.py::"
            "test_processor_alias_resolution_uses_definition_at_call_site"
        ),
        (
            "tests/guide/tools/test_single_path_architecture.py::"
            "test_processor_cannot_delegate_through_module_callable_alias"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_publish_recovers_partial_pending_write"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_revalidates_payload_after_final_key_check"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_rechecks_runtime_keys_after_publication_link"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_canonical_payload_rejects_replaced_intermediate_ancestor"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_rejects_dead_calls"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_rejects_"
            "empty_loop_calls"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_rejects_"
            "local_callable_alias"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_uses_"
            "reaching_alias_definition"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_resolves_"
            "module_callable_alias"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_rejects_shadowed_calls"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_payload_hash_rejects_"
            "replaced_intermediate_ancestor"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_executable_call_nodes_ignore_empty_comprehensions"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[allocation-requires-authorization-receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[authorization-receipt-history-complete]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[readiness-final-payload-revalidation]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[readiness-no-replace-commit]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_requires_allocation_"
            "authority_revalidation[persisted-contexts]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_requires_allocation_"
            "authority_revalidation[authorization-receipts]"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_runtime_private_key_cleanup_resumes_after_"
            "unlink_interruption"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_runtime_private_key_cleanup_rejects_forged_empty_tombstone"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_requires_signed_unused_key_destruction_receipt"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_runtime_private_key_cleanup_rejects_unbound_zero_file"
        ),
        (
            "tests/guide/tools/test_run_zero_api_runtime.py::"
            "test_runtime_private_key_unlink_interruption_"
            "preserves_retryable_key"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "        verified_receipts = "
            "_verify_authorization_receipts(\\n-"
            "        verified_receipts = "
            "accept_authorization_receipts(\\n-"
            "authorization receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "        _write_authorization_receipt(\\n"
            "            binding=binding,-"
            "        accept_authorization_receipt(\\n"
            "            binding=binding,-authorization receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/build_task11_readiness.py-"
            "        if not content:\\n"
            "            raise Task11ReadinessError(-"
            "        if False:\\n"
            "            raise Task11ReadinessError(-"
            "runtime key cleanup resume]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/build_task11_readiness.py-"
            "            _runtime_private_key_destruction_receipt(\\n"
            "                path=path,-"
            "            accept_private_key_destruction(\\n"
            "                path=path,-runtime key cleanup resume]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/build_task11_readiness.py-"
            "        _verify_runtime_signature(\\n"
            "            public_key=expected_public_key,\\n"
            "            signature=signature,\\n"
            "            domain="
            "_RUNTIME_PRIVATE_KEY_DESTRUCTION_SIGNATURE_DOMAIN,-"
            "        accept_runtime_signature(\\n"
            "            public_key=expected_public_key,\\n"
            "            signature=signature,\\n"
            "            domain="
            "_RUNTIME_PRIVATE_KEY_DESTRUCTION_SIGNATURE_DOMAIN,-"
            "runtime key cleanup resume]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/build_task11_readiness.py-"
            "        os.ftruncate(file_descriptor, 0)-"
            "        accept_unlinked_key(file_descriptor)-"
            "runtime key cleanup resume]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[runtime-key-consumption-order]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "        _verify_published_readiness_anchors(\\n-"
            "        accept_published_readiness_anchors(\\n-"
            "checkpoint authority]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "        _verify_persisted_attempt_contexts(\\n-"
            "        accept_persisted_attempt_contexts(\\n-"
            "authorization receipt]"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_checkpoint_rejects_precheckpoint_replay_from_new_epoch"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_checkpoint_authority_allows_resume_before_readiness"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "        _write_checkpoint_authority(\\n"
            "            binding,-"
            "        accept_checkpoint_authority(\\n"
            "            binding,-checkpoint authority]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "_canonical_bytes(immutable_authorization)-"
            "_canonical_bytes(authorization)-authorization receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "    \"created_at\",\\n})-"
            "    \"created_at\",\\n    \"state\",\\n})-"
            "authorization receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "    _write_bound_immutable_json(\\n"
            "        binding=receipt_binding,-"
            "    accept_bound_immutable_json(\\n"
            "        binding=receipt_binding,-authorization receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "    _write_bound_immutable_json(\\n"
            "        binding=authority_binding,-"
            "    accept_bound_immutable_json(\\n"
            "        binding=authority_binding,-checkpoint authority]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "            _write_attempt_context_witness(\\n"
            "                binding=binding,-"
            "            accept_attempt_context_witness(\\n"
            "                binding=binding,-authorization receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "        _write_attempt_context_witness(\\n"
            "            binding=binding,-"
            "        accept_attempt_context_witness(\\n"
            "            binding=binding,-authorization receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "            if witness_attempt_id is not None:\\n"
            "                raise AttemptLedgerError(-"
            "            if False:\\n"
            "                raise AttemptLedgerError(-"
            "authorization receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "    repository_root = _REPO_ROOT.resolve()-"
            "    repository_root = binding.path.parent-"
            "authorization receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "        os.link(\\n"
            "            temporary_binding.name,\\n"
            "            binding.name,-"
            "        os.replace(\\n"
            "            temporary_binding.name,\\n"
            "            binding.name,-immutable sidecar commit]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "        if len(current) >= len(data) or "
            "not data.startswith(current):-"
            "        if False:-immutable sidecar commit]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/build_task11_readiness.py-"
            "        if not content:\\n"
            "            raise Task11ReadinessError(-"
            "        if not content:\\n"
            "            return\\n"
            "        if not content:\\n"
            "            raise Task11ReadinessError(-"
            "runtime key cleanup resume]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/build_task11_readiness.py-"
            "\"key_inode\": key_metadata.st_ino,-"
            "\"key_inode\": 0,-runtime key cleanup resume]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/build_task11_readiness.py-"
            "        _require_runtime_private_keys_destroyed(\\n"
            "            fixture_runtime_private_key_path,-"
            "        accept_destroyed_runtime_private_keys(\\n"
            "            fixture_runtime_private_key_path,-"
            "runtime key cleanup receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/build_task11_readiness.py-"
            "            _verify_runtime_private_key_"
            "destruction_receipt_file(\\n-"
            "            accept_runtime_private_key_"
            "destruction_receipt_file(\\n-"
            "runtime key cleanup receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/build_task11_readiness.py-"
            "        verify_ledger_checkpoint_authority(\\n-"
            "        accept_ledger_checkpoint_authority(\\n-"
            "checkpoint authority]"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_ledger_lock_file_is_isolated_from_repository"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_ledger_lock_path_replacement_cannot_split_critical_section"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_ledger_lock_rejects_symlink_substitution"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_ledger_lock_root_replacement_cannot_split_critical_section"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "with _bound_external_ledger_lock(path, shared=shared):-"
            "with nullcontext():-lock inode binding]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "os.O_RDWR | os.O_CREAT | _NO_FOLLOW | _CLOSE_ON_EXEC-"
            "os.O_RDWR | os.O_CREAT | _CLOSE_ON_EXEC-"
            "lock inode binding]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "root = _lock_anchor_path()-"
            "root = _LOCK_DIRECTORY.parent-lock inode binding]"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_binds_repository_keys_and_ledger_source"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_manifest_validation_rejects_nested_repository_copy"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_runtime_browser_promotion_rejects_unbound_private_key_path"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_seal_rejects_unbound_private_key_path"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_rechecks_runtime_keys_immediately_before_publish"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_publish_rejects_parent_directory_replacement"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_checkpoint_rejects_rewritten_history_against_reviewed_manifest"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_runtime_private_key_cleanup_rejects_path_replacement"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_runtime_private_key_cleanup_rejects_parent_replacement"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_checkpoint_rejects_nested_repository_root"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_checkpoint_rejects_ledger_path_outside_repository"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_checkpoint_rejects_precheckpoint_replay_after_readiness_publish"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_ledger_rollback_cannot_allocate_a_second_attempt"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_allocation_rejects_output_root_outside_ledger_authority"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_readiness_binding_rejects_nested_protected_tree_substitution"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_rejects_sibling_manifest_path"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_rejects_sibling_symlink"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_rejects_symlinked_epoch_directory"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_canonical_payload_rejects_symlinked_ancestor"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_revalidates_protected_payload_before_publish"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_recovery_rolls_back_canonical_on_"
            "authority_failure"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_hashes_the_same_bytes_it_parses"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_requires_reviewed_sha256"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_accepts_matching_revision_qualified_path"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_readiness_requires_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_zero_api_summary_requires_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_ledger_read_rejects_ancestor_replacement_during_leaf_open"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_ledger_write_rejects_ancestor_replacement_during_atomic_replace"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-"
            "with _bound_ledger_path(path, create_parent=True) as binding:-"
            "with nullcontext() as binding:-ledger path binding]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/run_final_real_translation.py-"
            "usage_limiter = build_provider_usage_limiter(-"
            "usage_limiter = DailyUsageLimiter(-provider quota]"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_zero_api_summary_reuses_the_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_change_manifest_clis_require_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_task11_readiness_requires_external_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_release_readiness_branch_forwards_external_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_runtime_verifier_receives_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_sibling_candidate_manifest"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_symlinked_epoch_directory"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_payload_hash_rejects_symlinked_ancestor"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_hashes_the_same_bytes_it_parses"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_requires_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_accepts_matching_revision_"
            "qualified_manifest"
        ),
        (
            "tests/guide/runtime/test_runtime_http.py::"
            "test_chat_demo_query_uses_production_page_and_transport"
        ),
        (
            "tests/guide/runtime/test_runtime_http.py::"
            "test_http_session_waiters_do_not_exhaust_shared_threadpool"
        ),
        (
            "tests/guide/runtime/test_runtime_http.py::"
            "test_recording_query_cannot_replace_production_chat"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_authorization_rejects_forked_ledger_path"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_ledger_rejects_fabricated_consumed_state_before_completion"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_ledger_rejects_inserting_unrecorded_historical_failures"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_ledger_rejects_recomputed_tip_after_historical_state_deletion"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_ledger_rejects_rewriting_passed_translation_parent"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_payload_hash_rejects_repository_root_replacement"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_hashes_the_same_evidence_bytes_it_parses"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_rejects_noncanonical_epoch_evidence"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_payload_hash_rejects_repository_root_replacement"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_cli_requires_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_top_level_rejects_wrong_reviewed_sha256"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_rejects_jointly_forged_identity_and_"
            "challenge_digests"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_task12_execution_surface_includes_runtime_auth"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_task12_execution_surface_"
            "includes_zero_api_runtime"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_task12_execution_surface_"
            "matches_independent_audit"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_seals_external_runtime_private_key"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_preserves_preexisting_retry_key"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_runtime_browser_promotion_is_atomic_and_byte_identical"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_runtime_browser_promotion_rejects_invalid_staging_"
            "without_publish"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_runtime_browser_promotion_interruption_does_not_publish"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_runtime_browser_promotion_resumes_post_commit_key_cleanup"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_seal_rejects_surviving_runtime_private_key"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_derive_candidate_readiness_cannot_publish"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_runtime_private_key_paths_resolve_only_parent_alias"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_requires_two_distinct_runtime_"
            "public_keys[runtime_public_keys0]"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_requires_two_distinct_runtime_"
            "public_keys[runtime_public_keys1]"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_requires_two_distinct_runtime_"
            "public_keys[runtime_public_keys2]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_browser_preserves_consumed_health_challenge_"
            "original"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_browser_persists_identity_and_consumed_"
            "challenge_originals"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_browser_never_merges_typed_runtime_proof_as_a_"
            "mapping"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_jointly_forged_identity_and_"
            "challenge_digests"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_retry_authorization_revalidates_latest_zero_card_repair"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_attempt_context_binds_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_authorize_cli_requires_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_retry_authorization_rejects_fabricated_zero_card_repair"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_completion_rejects_context_bytes_different_from_parsed_object"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_completion_rejects_context_replaced_after_lock_entry"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_completion_revalidates_readiness_before_terminal_transition"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_consumption_rejects_context_bytes_different_from_parsed_object"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_consumption_rejects_context_replaced_after_lock_entry"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_consumption_rejects_evidence_drift_after_lock_entry"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_consumption_revalidates_readiness_before_ledger_transition"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_failed_completion_requires_existing_hashed_evidence"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_generic_compare_and_swap_cannot_reopen_consumed_authorization"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_runtime_bound_consumption_rejects_unregistered_signing_key"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_runtime_registration_abort_is_append_only_and_allows_restart"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_runtime_registration_is_single_active_ledger_transition"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_completion_waits_for_request_lifecycle_cleanup"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_reclassify_accepts_indexed_runner_startup_evidence"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_authorization_validates_repair_before_exclusive_"
            "ledger_lock"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_translation_completion_requires_verified_terminal_evidence"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_real_terminal_validators_reject_empty_evidence"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_atomic_ledger_write_cannot_follow_predictable_temp_symlink"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_allocation_ledger_failure_rolls_back_context_and_is_retryable"
        ),
        *(
            (
                "tests/guide/tools/test_attempt_ledger.py::"
                "test_terminal_evidence_tampering_is_rejected_on_every_read"
                f"[{reader}]"
            )
            for reader in ("ledger", "latest_context")
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_passed_attempt_cannot_remove_terminal_evidence_manifest"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_terminal_evidence_rejects_unrecorded_root_file"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_failure_reclassification_rejects_testcase_free_junit"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_failure_reclassification_rejects_wrong_regression_node"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_failure_reclassification_rejects_unreviewed_focused_nodes"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_failure_reclassification_rejects_forged_focused_node_identity"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_failure_reclassification_rejects_non_applicable_patch"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_requires_retry_repair_revalidation"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_requires_pre_decision_rejection_coverage"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_requires_pre_decision_rejection_coverage"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_allowed_bounded_clarification_has_zero_release_counters"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_sandbox_audit_records_kernel_denied_chromium_ipv6_probe"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_sandbox_audit_rejects_chromium_probe_denial_after_end"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_drain_canary_is_parent_marked_before_release"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_drain_canary_kills_nonquiescent_descendants"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_drain_child_requires_start_gate"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_sandbox_audit_rejects_child_marker_before_kernel_identity"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_capture_waits_for_every_required_marker_family"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_short_lived_fixture_canaries_do_not_emit_logger_markers"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_sandbox_audit_accepts_duplicate_only_known_chromium_probe"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_accepts_parent_observed_runtime_canary_order"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_accepts_parent_observed_runtime_canary_order"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_audit_rejects_marker_before_kernel_identity"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_audit_accepts_fixed_chromium_probe"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_audit_rejects_probe_without_kernel_denial"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_audit_rejects_probe_denial_after_end"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_is_ast_verified"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_reclassification_inventory_registers_chromium_probe_regression"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_binds_matrix_to_browser_bounded_messages"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_rejects_bounded_browser_message_drift"
        ),
        *(
            (
                "tests/guide/tools/test_build_task11_readiness.py::"
                "test_candidate_scope_includes_all_executable_change_roots"
                f"[{path}]"
            )
            for path in (
                "Dockerfile",
                "app/config.py",
                "app/main.py",
                "docker-compose.prod.yml",
                "init.sql",
                "nginx.conf",
                "pytest-guide.ini",
                "requirements-guide-browser-matrix.txt",
                "requirements-guide-runtime.txt",
                "start.sh",
                "tests/test_runtime_entry.py",
                "tools/rogue_paid_call.py",
            )
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_binds_matrix_to_browser_bounded_messages"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_bounded_browser_message_drift"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_non_string_bounded_message"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_attempt_09_reclassification_derives_planning_state_owner"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_attempt_09_reclassification_rejects_unbound_repair_patch"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_retry_authorization_revalidates_latest_planning_state_repair"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_retry_authorization_rejects_fabricated_planning_state_repair"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_input_replacement_after_validation"
        ),
        (
            "tests/guide/runtime/test_feedback_frontend.py::"
            "test_feedback_target_lookup_is_abortable_and_bounded"
        ),
        (
            "tests/guide/runtime/test_feedback_frontend.py::"
            "test_verified_version_commits_before_optional_feedback_lookup"
        ),
        (
            "tests/guide/runtime/test_frontend_scope.py::"
            "test_stream_resynchronizes_authoritative_version_before_turn_request"
        ),
        (
            "tests/guide/runtime/test_frontend_scope.py::"
            "test_version_sync_rejects_committed_turn_that_was_not_rendered"
        ),
        (
            "tests/guide/runtime/test_runtime_http.py::"
            "test_runtime_version_endpoint_reports_authoritative_committed_version"
        ),
        (
            "tests/guide/runtime/test_runtime_http.py::"
            "test_runtime_explicit_product_with_current_upload_persists_dormant_image_lane"
        ),
        *(
            (
                "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
                "test_legacy_frontend_audit_rejects_invalid_live_sse_lifecycle"
                f"[event_names{index}]"
            )
            for index in range(8)
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_readiness_rejects_non_epoch_output_path"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_saved_readiness_uses_one_ledger_snapshot"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_attempt_09_reclassification_binds_previous_turn_stream"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_attempt_09_reclassification_requires_current_focused_nodes"
        ),
        *(
            (
                "tests/guide/tools/test_run_task11_independent_audit.py::"
                "test_independent_audit_includes_root_runtime_inputs"
                f"[{path}]"
            )
            for path in (
                ".env.example",
                "Dockerfile",
                "docker-compose.prod.yml",
                "docker-compose.yml",
                "init.sql",
                "nginx.conf",
                "pytest-guide.ini",
                "requirements-guide-browser-matrix.txt",
                "requirements-guide-image.txt",
                "requirements-guide-runtime-test.txt",
                "requirements-guide-runtime.txt",
                "requirements.txt",
                "start.sh",
            )
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-            proof = "
            "_request_live_runtime_proof(-            proof = "
            "accept_unsigned_runtime_proof(-signed runtime proof]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-            "
            "validate_runtime_bound_attempt_attestation(-            "
            "accept_runtime_attestation(-terminal evidence]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_completed_release_browser_evidence_accepts_all_fourteen_turns"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_authorized_bounded_startup_failure_records_terminal_evidence"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_completed_release_browser_evidence_rederives_turn_counters"
        ),
        (
            "tests/guide/runtime/test_runtime_http.py::"
            "test_demo_page_uses_valid_scripted_presentation_contracts"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_nonlauncher_runtime_registration"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_image_fit_without_fit_contract"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_accepts_plan_bound_revision_upgrade"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_image_turns_prepare_real_upload_inputs"
            "[fixture-image-identity--expected_file_names0]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_image_turns_prepare_real_upload_inputs"
            "[fixture-image-fit-recommendation-"
            "\\u7ed9\\u6211\\u627e\\u4e00\\u6b3e\\u6700\\u9002"
            "\\u5408\\u6cb9\\u654f\\u808c\\u3001\\u6362\\u5b63"
            "\\u6cdb\\u7ea2\\u65f6\\u7528\\u7684\\u76f8\\u4f3c"
            "\\u7cbe\\u534e-expected_file_names1]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_image_turns_prepare_real_upload_inputs"
            "[fixture-multi-image-comparison-"
            "\\u6bd4\\u8f83\\u8fd9\\u4e24\\u5f20\\u56fe\\u91cc"
            "\\u7684\\u5546\\u54c1-expected_file_names2]"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_route_preserves_image_bundle_multipart_upload"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_chromium_disables_external_dns_transport"
        ),
    }
)
RECLASSIFICATION_REPLACED_EVIDENCE_NODES = frozenset(
    {
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_cli_requires_runtime_identity"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_ledger_lock_does_not_leave_a_repository_sibling"
        ),
        (
            "tests/guide/runtime/test_runtime_http.py::"
            "test_chat_demo_mode_uses_fixture_and_never_posts_feedback"
        ),
        (
            "tests/guide/runtime/test_runtime_http.py::"
            "test_recording_v1_serves_versioned_chat_snapshot"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_bounded_completion_rejects_fabricated_runtime_hashes"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_browser_child_rejects_failed_translation_parent"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_consumption_rechecks_plan_revision_circuit"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-            receipt = "
            "_consume_live_runtime_health_challenge(-            receipt = "
            "accept_caller_runtime_challenge(-live runtime challenge]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[tools/guide_gates/attempt_ledger.py-            "
            "validate_runtime_bound_attempt_attestation(-            "
            "accept_runtime_attestation(-bounded browser evidence]"
        ),
    }
)
RECLASSIFICATION_PATCH_PATHS = frozenset(
    {
        "app/static/chat.html",
        "tests/guide/runtime/test_feedback_frontend.py",
    }
)
RECLASSIFICATION_PATCH_SHA256 = (
    "5b81909146d5bcd06041da3c25063ec86c5f3212d754882062ed1e1fbf1b5f53"
)
PLANNING_RECLASSIFICATION_REGRESSION_NODE = (
    "tests/guide/tools/test_task11_production_path_matrix.py::"
    "test_persisted_image_similarity_prepares_scenario_inputs_before_routing"
)
PLANNING_PREDECESSOR_STREAM_SHA256 = (
    "af9e27575ce42ff8e5b01cb13d27598d6fa557d077744da6e0994ca0e0386d5a"
)
PLANNING_RECLASSIFICATION_FOCUSED_NODES = frozenset(
    {
        PLANNING_RECLASSIFICATION_REGRESSION_NODE,
        (
            "tests/guide/tools/test_task11_production_path_matrix.py::"
            "test_bounded_trajectory_contract_rejects_message_drift"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_allowed_bounded_clarification_has_zero_release_counters"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_binds_matrix_to_browser_bounded_messages"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_rejects_bounded_browser_message_drift"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_binds_matrix_to_browser_bounded_messages"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_bounded_browser_message_drift"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_non_string_bounded_message"
        ),
    }
)
PLANNING_RECLASSIFICATION_PATCH_PATHS = frozenset(
    {
        "app/guide/application/unified_guide_flow.py",
        "tests/guide/tools/test_task11_production_path_matrix.py",
    }
)
PLANNING_RECLASSIFICATION_PATCH_SHA256 = (
    "77cd54ac6dbbfd4cfe93149e0caa25b6b5a59f44f811e279e85ecbee10f2ac6e"
)
RUNTIME_SHELL_REPAIR_REGRESSION_NODES = frozenset(
    {
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_attempt_completed_can_rebind_evidence_directory"
        ),
        (
            "tests/guide/tools/test_run_bound_runtime.py::"
            "test_runtime_shell_assets_do_not_take_business_authority_lease"
        ),
    }
)
RUNTIME_SHELL_REPAIR_FOCUSED_MODULES = frozenset(
    {
        "tests/guide/tools/test_attempt_ledger.py",
        "tests/guide/tools/test_build_task11_readiness.py",
        "tests/guide/tools/test_run_bound_runtime.py",
        "tests/guide/tools/test_run_mainline_contract_browser_audit.py",
        "tests/guide/tools/test_run_task11_independent_audit.py",
    }
)
RUNTIME_SHELL_REPAIR_HISTORICAL_FOCUSED_MODULES = frozenset(
    {
        "tests/guide/tools/test_attempt_ledger.py",
        "tests/guide/tools/test_run_bound_runtime.py",
        "tests/guide/tools/test_run_mainline_contract_browser_audit.py",
        "tests/guide/tools/test_run_task11_independent_audit.py",
    }
)
RUNTIME_SHELL_REPAIR_RENAMED_EVIDENCE_NODES = {
    (
        "tests/guide/tools/test_attempt_ledger.py::"
        "test_runtime_request_lease_blocks_completion_until_response_finishes"
    ): (
        "tests/guide/tools/test_attempt_ledger.py::"
        "test_completion_waits_for_request_lifecycle_cleanup"
    ),
    (
        "tests/guide/tools/test_run_bound_runtime.py::"
        "test_consumed_runtime_rechecks_readiness_before_each_business_request"
    ): (
        "tests/guide/tools/test_run_bound_runtime.py::"
        "test_runtime_version_check_uses_lightweight_authority_check"
    ),
    (
        "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
        "test_fixture_cli_requires_runtime_identity"
    ): (
        "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
        "test_fixture_cli_requires_runtime_identity_and_manifest_hash"
    ),
}
RUNTIME_SHELL_REPAIR_PATCH_PATHS = frozenset(
    {
        "tools/guide_gates/attempt_ledger.py",
        "tools/guide_gates/run_bound_runtime.py",
    }
)
RUNTIME_SHELL_REPAIR_PATCH_SHA256 = (
    "aa6fb2cfb1d1879e5ac23d86ebc47976899e676632ddbe1ac78a99ae4782b16c"
)
RUNTIME_REQUEST_AUTHORITY_REPAIR_REGRESSION_NODES = frozenset(
    {
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_runtime_request_authority_does_not_reverify_"
            "complete_readiness"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_completion_waits_for_request_lifecycle_cleanup"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_reclassify_accepts_indexed_runner_startup_evidence"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_authorization_validates_repair_before_exclusive_"
            "ledger_lock"
        ),
        (
            "tests/guide/tools/test_run_bound_runtime.py::"
            "test_runtime_releases_ledger_lock_before_entering_application"
        ),
        (
            "tests/guide/tools/test_run_bound_runtime.py::"
            "test_runtime_version_check_uses_lightweight_authority_check"
        ),
    }
)
RUNTIME_REQUEST_AUTHORITY_REPAIR_FOCUSED_MODULES = frozenset(
    {
        "tests/guide/tools/test_attempt_ledger.py",
        "tests/guide/tools/test_build_task11_readiness.py",
        "tests/guide/tools/test_run_bound_runtime.py",
        "tests/guide/tools/test_run_mainline_contract_browser_audit.py",
        "tests/guide/tools/test_run_task11_independent_audit.py",
    }
)
RUNTIME_REQUEST_AUTHORITY_REPAIR_PATCH_PATHS = frozenset(
    {
        "tools/guide_gates/attempt_ledger.py",
        "tools/guide_gates/run_bound_runtime.py",
    }
)


class _AuditStaticReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: set[str] = set()

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attribute = "src" if tag == "script" else "href" if tag == "link" else None
        if attribute is None:
            return
        value = dict(attrs).get(attribute)
        if not isinstance(value, str):
            return
        parsed = urlsplit(value)
        if (
            parsed.scheme
            or parsed.netloc
            or not parsed.path.startswith("/static/")
        ):
            return
        self.references.add(
            PurePosixPath(
                "app/static",
                parsed.path.removeprefix("/static/"),
            ).as_posix()
        )


def _require_local_static_dependencies(
    *,
    root: Path,
    protected_paths: Sequence[str],
) -> None:
    static_dependencies: set[str] = set()
    for relative in protected_paths:
        if (
            not relative.startswith("app/static/")
            or not relative.endswith(".html")
        ):
            continue
        parser = _AuditStaticReferenceParser()
        parser.feed((root / relative).read_text(encoding="utf-8"))
        static_dependencies.update(
            dependency
            for dependency in parser.references
            if (root / dependency).is_file()
        )
    _require(
        static_dependencies <= set(protected_paths),
        "candidate manifest omits a local static dependency",
    )
_TEST_FIXTURE_PATTERN = re.compile(
    r"tests/fixtures/guide/[A-Za-z0-9_./-]+"
)
SUMMARY_ZERO_FIELDS = (
    "actual_equivalence_failure_count",
    "bounded_failure_count",
    "pre_decision_rejection_failure_count",
    "compiler_bypass_count",
    "compiler_call_count_violation_count",
    "structured_understanding_injection_count",
    "direct_router_bypass_count",
    "legacy_entrypoint_count",
    "router_call_count_violation_count",
    "decision_identity_violation_count",
    "selected_processor_invocation_count_violation_count",
    "nonselected_processor_invocation_count",
    "execution_result_count_violation_count",
    "reducer_call_count_violation_count",
    "processor_state_write_count",
    "event_state_projection_count",
    "state_save_count_violation_count",
    "terminal_contract_failure_count",
    "state_transition_failure_count",
    "outbound_network_attempt_count",
    "provider_call_count",
)
TRACE_ZERO_FIELDS = (
    "structured_understanding_injection_count",
    "direct_router_bypass_count",
    "legacy_entrypoint_count",
    "decision_identity_violation_count",
    "processor_state_write_count",
    "event_state_projection_count",
    "provider_call_count",
    "outbound_network_attempt_count",
)
PRODUCTION_ACCEPTED_TURN_COUNT = 176
PRODUCTION_MATRIX_TURN_COUNT = 177
PRE_DECISION_REJECTION_COUNT = 1
RUNTIME_LAYER_ORDER = [
    "translation",
    "compiler",
    "router",
    "processor",
    "reducer",
    "sqlite",
    "sse",
]
READINESS_COMPLETION_BINDINGS = {
    "step_0_passed": "step_0_passed",
    "step_0_5_passed": "step_0_5_passed",
    "step_4_5_passed": "step_4_5_passed",
    "step_4_6_passed": "step_4_6_passed",
    "affected_zero_api_passed": "affected_zero_api_passed",
    "single_path_architecture_passed": (
        "single_path_architecture_passed"
    ),
    "production_path_matrix_passed": (
        "production_path_matrix_passed"
    ),
    "desktop_fixture_passed": "desktop_fixture_passed",
    "mobile_fixture_passed": "mobile_fixture_passed",
}
PROCESSOR_SOURCE_ROOTS = {
    "app/guide/application/text_recommendation_flow.py": (
        "TextRecommendationOrchestrator",
        "execute",
    ),
    "app/guide/application/image_recommendation_flow.py": (
        "ImageRecommendationOrchestrator",
        "execute",
    ),
    "app/guide/application/consultation_chat_flow.py": (
        "ConsultationChatFlow",
        "execute",
    ),
}
UNIFIED_FLOW_SOURCE_PATH = (
    "app/guide/application/unified_guide_flow.py"
)
BRIDGE_SYMBOLS = frozenset(
    {
        "ChatOwner",
        "bind_execution_profile_owner",
        "classify_chat_owner",
        "collect_guide_chat_response",
        "compatibility_dispatch",
        "compiler_bridge",
        "from_user_turn",
        "legacy_dispatch",
        "project_event_to_state",
        "route_bridge",
    }
)
LEGACY_FLAG_NAMES = frozenset(
    {
        "GUIDE_USE_LEGACY_ROUTER",
        "GUIDE_USE_UNIFIED_ROUTER",
        "LEGACY_GUIDE",
        "USE_LEGACY_GUIDE",
        "USE_UNIFIED_ROUTER",
    }
)
REQUIRED_BROWSER_FILES = frozenset(
    {
        "request.json",
        "stream.sse",
        "presentation-contract.json",
        "terminal-dom.json",
        "screenshot.png",
        "console.json",
        "network.json",
        "sandbox-audit.json",
    }
)
RELEVANT_PREFIXES = (
    "app/",
    "tests/",
    "tools/",
    "docs/superpowers/plans/",
)
RELEVANT_ROOT_FILES = frozenset(
    {
        ".env.example",
        "Dockerfile",
        "docker-compose.prod.yml",
        "docker-compose.yml",
        "docker-compose.yaml",
        "init.sql",
        "nginx.conf",
        "pytest-guide.ini",
        "requirements-guide-browser-matrix.txt",
        "requirements-guide-image.txt",
        "requirements-guide-runtime-test.txt",
        "requirements-guide-runtime.txt",
        "requirements.txt",
        "start.sh",
    }
)
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
RUNTIME_IDENTITY_SCHEMA = "guide-zero-api-runtime-identity-v1"
RUNTIME_CHALLENGE_SCHEMA = "guide-zero-api-runtime-challenge-v1"
RUNTIME_IDENTITY_ARTIFACT = "runtime-identity.json"
CONSUMED_CHALLENGE_ARTIFACT = (
    "consumed-runtime-health-challenge.json"
)
TASK12_TOOL_PATHS = (
    "tools/guide_gates/attempt_ledger.py",
    "tools/guide_gates/build_responsibility_matrix.py",
    "tools/guide_gates/build_task11_readiness.py",
    "tools/guide_gates/record_manual_screenshot_review.py",
    "tools/guide_gates/replay_final_real_backend.py",
    "tools/guide_gates/run_bound_runtime.py",
    "tools/guide_gates/runtime_auth.py",
    "tools/guide_gates/run_final_real_translation.py",
    "tools/guide_gates/run_final_release_gate.py",
    "tools/guide_gates/run_mainline_contract_browser_audit.py",
    "tools/guide_gates/run_zero_api_runtime.py",
)
TASK12_TEST_PATHS = (
    "tests/guide/tools/test_build_responsibility_matrix.py",
    "tests/guide/tools/test_final_real_translation.py",
    "tests/guide/tools/test_replay_final_real_backend.py",
    "tests/guide/tools/test_final_release_gate.py",
    "tests/guide/tools/test_record_manual_screenshot_review.py",
)
TASK12_FIXTURE_PATHS = (
    "tests/fixtures/guide/final_release/"
    "real_translation_12x4_v5.jsonl",
)
TASK12_RUNTIME_DATA_PATHS = (
    "data/canonical/core_products_v1_manifest.json",
    "data/canonical/core_products_v1.jsonl",
    "data/canonical/seed_product_images_v1_manifest.json",
    "data/canonical/seed_product_images_v1.jsonl",
)
BROWSER_CANONICAL_DATA_PATHS = (
    *TASK12_RUNTIME_DATA_PATHS,
    "data/canonical/controlled_product_aliases_v1_manifest.json",
    "data/canonical/controlled_product_aliases_v1.jsonl",
    "data/guide_category_facts/category_facts_v1_manifest.json",
    (
        "data/guide_category_facts/"
        "category_facts_v1."
        "9e037e77a4f7dbf3c5eb67f18850ff70fa33748131c19f3c7f3ceaa023f859bb."
        "jsonl"
    ),
    (
        "data/guide_product_display_bindings/v1/"
        "product_display_bindings_v1_manifest.json"
    ),
    (
        "data/guide_product_display_bindings/v1/"
        "product_display_bindings_v1."
        "1c4c8b655862cace29f62d9e7e14abf111668434572dbd8ddb902c8bf5b45d31."
        "jsonl"
    ),
    (
        "data/guide_selection_concepts/v2/"
        "selection_concepts_v1_manifest.json"
    ),
    (
        "data/guide_selection_concepts/v2/"
        "selection_concepts_v1."
        "0642ea8067325c7f3aed8ffbb884d5415ff42c9163b634def913f5de2a24e4d5."
        "jsonl"
    ),
    "data/guide_merchant_claims/merchant_claims_v1_manifest.json",
    (
        "data/guide_merchant_claims/"
        "merchant_claims_v1."
        "8b90f33d45368c269076d96a8b0ca76fd1c5fcac988fd96cc93937da7d4207fd."
        "jsonl"
    ),
)
ALLOWED_BROWSER_RESOURCE_TYPES = frozenset({
    "document",
    "eventsource",
    "fetch",
    "font",
    "image",
    "manifest",
    "media",
    "other",
    "script",
    "stylesheet",
    "texttrack",
    "websocket",
    "xhr",
})
MAX_SCREENSHOT_FILE_BYTES = 64 * 1024 * 1024
MAX_SCREENSHOT_WIDTH = 8192
MAX_SCREENSHOT_HEIGHT = 32768
MAX_SCREENSHOT_PIXELS = 50_000_000
CHROMIUM_IPV6_PROBE_TARGET = "[2001:4860:4860::8888]:443"


class Task11IndependentAuditError(RuntimeError):
    """Raised when a required Task 11 fact cannot be proved."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Task11IndependentAuditError(message)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _required_int(
    payload: Mapping[str, object],
    key: str,
    *,
    label: str,
) -> int:
    value = payload.get(key)
    _require(_is_int(value), f"{label} field {key} is invalid")
    return int(value)


def _required_zero(
    payload: Mapping[str, object],
    key: str,
    *,
    label: str,
) -> None:
    _require(
        _required_int(payload, key, label=label) == 0,
        f"{label} field {key} must be zero",
    )


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and HEX_64.fullmatch(value) is not None


def _digest_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _require_no_symlink_components(
    path: Path,
    *,
    label: str,
    trusted_root: Path | None = None,
) -> Path:
    candidate = path.absolute()
    if trusted_root is None:
        current = Path(candidate.anchor)
        components = candidate.parts[1:]
    else:
        current = trusted_root.resolve()
        try:
            components = candidate.relative_to(current).parts
        except ValueError as exc:
            raise Task11IndependentAuditError(
                f"{label} escapes the trusted root"
            ) from exc
    try:
        for component in components:
            current /= component
            _require(
                not stat.S_ISLNK(os.lstat(current).st_mode),
                f"{label} path contains a symlink",
            )
    except OSError as exc:
        raise Task11IndependentAuditError(
            f"{label} is missing: {candidate}"
        ) from exc
    return candidate


def _read_regular_file_once(path: Path, *, label: str) -> bytes:
    candidate = _require_no_symlink_components(path, label=label)
    directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    file_flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_descriptor: int | None = None
    file_descriptor: int | None = None
    try:
        directory_descriptor = os.open(
            candidate.anchor,
            directory_flags,
        )
        for component in candidate.parts[1:-1]:
            next_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        file_descriptor = os.open(
            candidate.name,
            file_flags,
            dir_fd=directory_descriptor,
        )
        opened = os.fstat(file_descriptor)
        _require(
            stat.S_ISREG(opened.st_mode)
            and opened.st_uid == os.getuid()
            and opened.st_nlink == 1,
            f"{label} is invalid",
        )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after_read = os.fstat(file_descriptor)
        named = os.stat(
            candidate.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise Task11IndependentAuditError(
            f"{label} is invalid"
        ) from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)
    _require(
        stat.S_ISREG(named.st_mode)
        and (opened.st_dev, opened.st_ino)
        == (after_read.st_dev, after_read.st_ino)
        and (opened.st_dev, opened.st_ino)
        == (named.st_dev, named.st_ino)
        and opened.st_size == after_read.st_size
        and opened.st_mtime_ns == after_read.st_mtime_ns,
        f"{label} changed during read",
    )
    return b"".join(chunks)


def _input_file(
    path: str | Path,
    *,
    label: str,
    trusted_root: Path | None = None,
) -> Path:
    supplied = Path(path)
    if trusted_root is not None:
        candidate = _require_no_symlink_components(
            supplied,
            label=label,
            trusted_root=trusted_root,
        )
    else:
        if supplied.is_symlink():
            raise Task11IndependentAuditError(
                f"{label} path contains a symlink"
            )
        candidate = supplied.resolve()
    if not candidate.is_file():
        raise Task11IndependentAuditError(f"{label} is missing: {candidate}")
    return candidate


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Task11IndependentAuditError(
            f"{label} is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise Task11IndependentAuditError(f"{label} must be an object")
    return value


def _load_list(path: Path, *, label: str) -> list[Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Task11IndependentAuditError(
            f"{label} is not valid JSON"
        ) from exc
    if not isinstance(value, list):
        raise Task11IndependentAuditError(f"{label} must be a list")
    return value


def _literal_string_keyword(
    call: ast.Call,
    *,
    name: str,
    label: str,
) -> str:
    values = [
        keyword.value
        for keyword in call.keywords
        if keyword.arg == name
    ]
    _require(
        len(values) == 1
        and isinstance(values[0], ast.Constant)
        and isinstance(values[0].value, str),
        f"{label} {name} is not a literal string",
    )
    return str(values[0].value)


def _optional_literal_string_keyword(
    call: ast.Call,
    *,
    name: str,
    label: str,
) -> str | None:
    values = [
        keyword.value
        for keyword in call.keywords
        if keyword.arg == name
    ]
    _require(
        len(values) <= 1,
        f"{label} {name} is duplicated",
    )
    if not values:
        return None
    value = values[0]
    _require(
        isinstance(value, ast.Constant)
        and (value.value is None or isinstance(value.value, str)),
        f"{label} {name} is not an optional literal string",
    )
    return value.value


def _bounded_browser_trajectory_messages(
    root: Path,
) -> tuple[tuple[str, str, str], ...]:
    path = root / BOUNDED_BROWSER_TOOL_PATH
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise Task11IndependentAuditError(
            "bounded browser trajectory source is invalid"
        ) from exc
    assignments = [
        statement.value
        for statement in tree.body
        if isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "BOUNDED_TRAJECTORIES"
            for target in statement.targets
        )
    ]
    _require(
        len(assignments) == 1
        and isinstance(assignments[0], (ast.Tuple, ast.List)),
        "bounded browser trajectory declaration is invalid",
    )
    observed: list[tuple[str, str, str]] = []
    for trajectory_index, trajectory_node in enumerate(
        assignments[0].elts
    ):
        label = f"bounded browser trajectory {trajectory_index}"
        _require(
            isinstance(trajectory_node, ast.Call),
            f"{label} is invalid",
        )
        trajectory_id = _literal_string_keyword(
            trajectory_node,
            name="trajectory_id",
            label=label,
        )
        turns = [
            keyword.value
            for keyword in trajectory_node.keywords
            if keyword.arg == "turns"
        ]
        _require(
            len(turns) == 1
            and isinstance(turns[0], (ast.Tuple, ast.List)),
            f"{label} turns are invalid",
        )
        for turn_index, turn_node in enumerate(turns[0].elts):
            turn_label = f"{label} turn {turn_index}"
            _require(
                isinstance(turn_node, ast.Call),
                f"{turn_label} is invalid",
            )
            turn_id = _literal_string_keyword(
                turn_node,
                name="turn_id",
                label=turn_label,
            )
            message = _literal_string_keyword(
                turn_node,
                name="message",
                label=turn_label,
            )
            observed.append(
                (
                    trajectory_id,
                    f"{trajectory_id}-{turn_id}",
                    message,
                )
            )
    _require(
        len(observed) == 9
        and len({case_id for _, case_id, _ in observed}) == 9,
        "bounded browser trajectory inventory is invalid",
    )
    return tuple(observed)


def _bounded_browser_trajectory_expectations(
    root: Path,
) -> tuple[tuple[str, str, str | None], ...]:
    path = root / BOUNDED_BROWSER_TOOL_PATH
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise Task11IndependentAuditError(
            "bounded browser trajectory source is invalid"
        ) from exc
    assignments = [
        statement.value
        for statement in tree.body
        if isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "BOUNDED_TRAJECTORIES"
            for target in statement.targets
        )
    ]
    _require(
        len(assignments) == 1
        and isinstance(assignments[0], (ast.Tuple, ast.List)),
        "bounded browser trajectory declaration is invalid",
    )
    observed: list[tuple[str, str, str | None]] = []
    for trajectory_index, trajectory_node in enumerate(
        assignments[0].elts
    ):
        label = f"bounded browser trajectory {trajectory_index}"
        _require(
            isinstance(trajectory_node, ast.Call),
            f"{label} is invalid",
        )
        trajectory_id = _literal_string_keyword(
            trajectory_node,
            name="trajectory_id",
            label=label,
        )
        turns = [
            keyword.value
            for keyword in trajectory_node.keywords
            if keyword.arg == "turns"
        ]
        _require(
            len(turns) == 1
            and isinstance(turns[0], (ast.Tuple, ast.List)),
            f"{label} turns are invalid",
        )
        for turn_index, turn_node in enumerate(turns[0].elts):
            turn_label = f"{label} turn {turn_index}"
            _require(
                isinstance(turn_node, ast.Call),
                f"{turn_label} is invalid",
            )
            turn_id = _literal_string_keyword(
                turn_node,
                name="turn_id",
                label=turn_label,
            )
            turn_expected_mode = _literal_string_keyword(
                turn_node,
                name="expected_mode",
                label=turn_label,
            )
            turn_expected_recommendation_mode = (
                _optional_literal_string_keyword(
                    turn_node,
                    name="expected_recommendation_mode",
                    label=turn_label,
                )
            )
            observed.append(
                (
                    f"{trajectory_id}-{turn_id}",
                    turn_expected_mode,
                    turn_expected_recommendation_mode,
                )
            )
    _require(
        len(observed) == 9
        and len({case_id for case_id, _, _ in observed}) == 9,
        "bounded browser trajectory expectations are invalid",
    )
    return tuple(observed)


def _validate_bounded_trajectory_messages(
    *,
    root: Path,
    cases_path: Path,
) -> tuple[tuple[str, str, str], ...]:
    try:
        cases = [
            json.loads(line)
            for line in cases_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Task11IndependentAuditError(
            "bounded trajectory messages are invalid"
        ) from exc
    matrix_messages_list: list[tuple[str, str, str]] = []
    for case in cases:
        if (
            not isinstance(case, dict)
            or case.get("partition") != "bounded"
            or case.get("bounded") is not True
        ):
            continue
        trajectory_id = case.get("trajectory_id")
        case_id = case.get("case_id")
        message = case.get("message")
        _require(
            isinstance(trajectory_id, str)
            and bool(trajectory_id)
            and isinstance(case_id, str)
            and bool(case_id)
            and isinstance(message, str),
            "bounded trajectory messages are invalid",
        )
        matrix_messages_list.append(
            (trajectory_id, case_id, message)
        )
    matrix_messages = tuple(matrix_messages_list)
    _require(
        len(matrix_messages) == 9
        and len({case_id for _, case_id, _ in matrix_messages}) == 9,
        "bounded trajectory messages are invalid",
    )
    browser_messages = _bounded_browser_trajectory_messages(root)
    _require(
        matrix_messages == browser_messages,
        "production matrix and browser bounded trajectory messages differ",
    )
    matrix_expectations: list[tuple[str, str, str | None]] = []
    for case in cases:
        if (
            not isinstance(case, dict)
            or case.get("partition") != "bounded"
            or case.get("bounded") is not True
        ):
            continue
        meaning = case.get("meaning")
        _require(
            isinstance(case.get("case_id"), str)
            and isinstance(case.get("expected_processor"), str)
            and isinstance(meaning, dict),
            "bounded trajectory expectations are invalid",
        )
        recommendation_mode = meaning.get("recommendation_mode")
        _require(
            recommendation_mode is None
            or isinstance(recommendation_mode, str),
            "bounded trajectory recommendation mode is invalid",
        )
        matrix_expectations.append(
            (
                str(case["case_id"]),
                str(case["expected_processor"]),
                recommendation_mode,
            )
        )
    _require(
        tuple(matrix_expectations)
        == _bounded_browser_trajectory_expectations(root),
        "bounded trajectory expectations differ",
    )
    return matrix_messages


def _relative_path(value: object, *, label: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{label} is invalid")
    raw = str(value)
    pure = PurePosixPath(raw)
    _require(
        "\\" not in raw
        and not pure.is_absolute()
        and ".." not in pure.parts
        and pure.as_posix() == raw
        and raw not in {".", ""},
        f"{label} is not a normalized repository path: {raw}",
    )
    return raw


def _path_list(
    payload: Mapping[str, object],
    key: str,
) -> list[str]:
    values = payload.get(key)
    _require(isinstance(values, list), f"manifest field {key} is invalid")
    normalized = [
        _relative_path(value, label=f"manifest {key} item")
        for value in values
    ]
    _require(
        normalized == sorted(normalized)
        and len(normalized) == len(set(normalized)),
        f"manifest field {key} must be sorted and unique",
    )
    return normalized


def _excluded_patterns(payload: Mapping[str, object]) -> list[str]:
    values = payload.get("excluded_paths")
    _require(
        isinstance(values, list),
        "manifest field excluded_paths is invalid",
    )
    patterns: list[str] = []
    for value in values:
        _require(
            isinstance(value, str) and bool(value),
            "manifest excluded path pattern is invalid",
        )
        raw = str(value)
        _require(
            not any(character in raw for character in "*?[")
            or raw in {".tmp-*", "debug-*.md"},
            "candidate manifest contains a production path exclusion",
        )
        normalized = raw[:-1] if raw.endswith("/") else raw
        _relative_path(
            normalized,
            label="manifest excluded path pattern",
        )
        patterns.append(raw)
    _require(
        patterns == sorted(patterns)
        and len(patterns) == len(set(patterns)),
        "manifest field excluded_paths must be sorted and unique",
    )
    _require(
        not any(
            PurePosixPath(
                pattern[:-1] if pattern.endswith("/") else pattern
            ).parts[0]
            in {"app", "tools", "tests"}
            for pattern in patterns
        ),
        "candidate manifest contains a production path exclusion",
    )
    return patterns


def _git(
    root: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=check,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Task11IndependentAuditError(
            "git evidence is unavailable"
        ) from exc


def _git_blob(root: Path, revision: str, relative: str) -> bytes | None:
    completed = _git(
        root,
        "show",
        f"{revision}:{relative}",
        check=False,
    )
    if completed.returncode == 0:
        return completed.stdout
    return None


def _canonical_payload_hash(root: Path, paths: Sequence[str]) -> str:
    visible_root_path = root.absolute()
    directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    file_flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(visible_root_path, directory_flags)
    except OSError as exc:
        raise Task11IndependentAuditError(
            "protected repository root is invalid"
        ) from exc
    digest = sha256()
    try:
        root_identity = os.fstat(root_fd)
        _require(
            stat.S_ISDIR(root_identity.st_mode)
            and root_identity.st_uid == os.getuid(),
            "protected repository root is invalid",
        )
        for relative in sorted(paths):
            relative_path = PurePosixPath(relative)
            _require(
                not relative_path.is_absolute()
                and bool(relative_path.parts)
                and all(
                    component not in {"", ".", ".."}
                    for component in relative_path.parts
                ),
                f"protected path is invalid: {relative}",
            )
            ancestor_fds = [os.dup(root_fd)]
            ancestor_components: list[str] = []
            file_fd: int | None = None
            try:
                for component in relative_path.parts[:-1]:
                    next_fd = os.open(
                        component,
                        directory_flags,
                        dir_fd=ancestor_fds[-1],
                    )
                    opened_ancestor = os.fstat(next_fd)
                    named_ancestor = os.stat(
                        component,
                        dir_fd=ancestor_fds[-1],
                        follow_symlinks=False,
                    )
                    if (
                        not stat.S_ISDIR(opened_ancestor.st_mode)
                        or opened_ancestor.st_uid != os.getuid()
                        or not os.path.samestat(
                            opened_ancestor,
                            named_ancestor,
                        )
                    ):
                        os.close(next_fd)
                        raise Task11IndependentAuditError(
                            f"protected ancestor changed: {relative}"
                        )
                    ancestor_fds.append(next_fd)
                    ancestor_components.append(component)
                file_fd = os.open(
                    relative_path.parts[-1],
                    file_flags,
                    dir_fd=ancestor_fds[-1],
                )
                opened = os.fstat(file_fd)
                _require(
                    stat.S_ISREG(opened.st_mode)
                    and opened.st_uid == os.getuid()
                    and opened.st_nlink == 1,
                    f"protected path is invalid: {relative}",
                )
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(file_fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after_read = os.fstat(file_fd)
                named = os.stat(
                    relative_path.parts[-1],
                    dir_fd=ancestor_fds[-1],
                    follow_symlinks=False,
                )
                for index, component in enumerate(ancestor_components):
                    opened_ancestor = os.fstat(ancestor_fds[index + 1])
                    named_ancestor = os.stat(
                        component,
                        dir_fd=ancestor_fds[index],
                        follow_symlinks=False,
                    )
                    _require(
                        stat.S_ISDIR(opened_ancestor.st_mode)
                        and opened_ancestor.st_uid == os.getuid()
                        and os.path.samestat(
                            opened_ancestor,
                            named_ancestor,
                        ),
                        f"protected ancestor changed: {relative}",
                    )
            except OSError as exc:
                raise Task11IndependentAuditError(
                    f"protected path is invalid: {relative}"
                ) from exc
            finally:
                if file_fd is not None:
                    os.close(file_fd)
                for descriptor in reversed(ancestor_fds):
                    os.close(descriptor)
            _require(
                stat.S_ISREG(named.st_mode)
                and (opened.st_dev, opened.st_ino)
                == (after_read.st_dev, after_read.st_ino)
                and (opened.st_dev, opened.st_ino)
                == (named.st_dev, named.st_ino)
                and opened.st_size == after_read.st_size
                and opened.st_mtime_ns == after_read.st_mtime_ns,
                f"protected path changed during read: {relative}",
            )
            encoded_path = relative.encode("utf-8")
            content = b"".join(chunks)
            digest.update(str(len(encoded_path)).encode("ascii"))
            digest.update(b":")
            digest.update(encoded_path)
            digest.update(str(len(content)).encode("ascii"))
            digest.update(b":")
            digest.update(content)
        try:
            visible_identity = os.stat(
                visible_root_path,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise Task11IndependentAuditError(
                "repository root changed during payload hash"
            ) from exc
        _require(
            stat.S_ISDIR(visible_identity.st_mode)
            and (root_identity.st_dev, root_identity.st_ino)
            == (visible_identity.st_dev, visible_identity.st_ino),
            "repository root changed during payload hash",
        )
        return digest.hexdigest()
    finally:
        os.close(root_fd)


def _excluded(relative: str, patterns: Sequence[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/") and (
            relative == pattern.rstrip("/") or relative.startswith(pattern)
        ):
            return True
        if fnmatch.fnmatchcase(relative, pattern):
            return True
    return False


def _is_relevant_change_path(relative: str) -> bool:
    return relative in RELEVANT_ROOT_FILES or relative.startswith(
        RELEVANT_PREFIXES
    )


def _changed_paths(root: Path, revision: str) -> set[str]:
    tracked = _git(
        root,
        "diff",
        "--name-only",
        "-z",
        revision,
        "--",
    ).stdout
    untracked = _git(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    ).stdout
    paths: set[str] = set()
    for raw in (tracked + untracked).split(b"\0"):
        if not raw:
            continue
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Task11IndependentAuditError(
                "git changed path is not UTF-8"
            ) from exc
        paths.add(_relative_path(decoded, label="git changed path"))
    return paths


def _production_diff_hash(
    *,
    root: Path,
    revision: str,
    change_paths: Sequence[str],
) -> str:
    digest = sha256()
    for relative in sorted(change_paths):
        base = _git_blob(root, revision, relative)
        current_path = root / relative
        current = current_path.read_bytes() if current_path.is_file() else None
        _require(
            not current_path.is_symlink(),
            f"changed path is a symlink: {relative}",
        )
        if base is None and current is not None:
            status = b"A"
        elif base is not None and current is None:
            status = b"D"
        elif base is not None and current is not None and base != current:
            status = b"M"
        else:
            raise Task11IndependentAuditError(
                f"manifest change path has no production diff: {relative}"
            )
        encoded = relative.encode("utf-8")
        digest.update(str(len(encoded)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded)
        digest.update(status)
        for content in (base, current):
            if content is None:
                digest.update(b"-1:")
            else:
                digest.update(str(len(content)).encode("ascii"))
                digest.update(b":")
                digest.update(content)
    return digest.hexdigest()


def _validate_manifest(
    *,
    root: Path,
    path: Path,
    payload: Mapping[str, object],
    raw_bytes: bytes,
    expected_manifest_sha256: str,
) -> tuple[str, str]:
    _require_no_symlink_components(
        path,
        label="candidate manifest",
        trusted_root=root,
    )
    try:
        parsed = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Task11IndependentAuditError(
            "candidate manifest bytes are invalid"
        ) from exc
    _require(
        isinstance(parsed, dict) and parsed == payload,
        "candidate manifest bytes do not match parsed payload",
    )
    _require(
        payload.get("schema_version") == MANIFEST_SCHEMA,
        "candidate manifest schema is invalid",
    )
    actual_root = Path(
        _git(root, "rev-parse", "--show-toplevel")
        .stdout.decode()
        .strip()
    ).resolve()
    _require(
        payload.get("repository_root") == str(root.resolve())
        and actual_root == root.resolve(),
        "candidate manifest repository root is invalid",
    )
    runtime_public_keys = payload.get(
        "fixture_runtime_public_keys"
    )
    _require(
        isinstance(runtime_public_keys, list)
        and len(runtime_public_keys) == 2
        and all(
            isinstance(runtime_public_key, str)
            for runtime_public_key in runtime_public_keys
        )
        and len(set(runtime_public_keys)) == 2,
        "candidate manifest runtime public keys are invalid",
    )
    for runtime_public_key in runtime_public_keys:
        _decode_runtime_provenance_value(
            runtime_public_key,
            length=32,
        )
    _require(
        isinstance(payload.get("plan_revision"), str)
        and payload["plan_revision"],
        "candidate manifest plan revision is invalid",
    )
    repair_epoch = payload.get("repair_epoch")
    epoch_match = re.fullmatch(
        r"repair-epoch-(\d+)",
        path.parent.name,
    )
    _require(
        isinstance(repair_epoch, int)
        and not isinstance(repair_epoch, bool)
        and repair_epoch > 0
        and epoch_match is not None
        and int(epoch_match.group(1)) == repair_epoch,
        "candidate manifest repair epoch is invalid",
    )
    _require(
        _candidate_manifest_path_is_valid(
            root=root,
            path=path,
            repair_epoch=repair_epoch,
            plan_revision=payload.get("plan_revision"),
        ),
        "candidate manifest canonical path is invalid",
    )
    _require(
        _is_digest(expected_manifest_sha256)
        and sha256(raw_bytes).hexdigest() == expected_manifest_sha256,
        "candidate manifest reviewed SHA-256 is invalid",
    )
    candidate_head = payload.get("candidate_head")
    _require(
        isinstance(candidate_head, str)
        and HEX_40.fullmatch(candidate_head) is not None,
        "candidate manifest head is invalid",
    )
    actual_head = _git(root, "rev-parse", "HEAD").stdout.decode().strip()
    _require(
        candidate_head == actual_head,
        "candidate manifest head does not match repository HEAD",
    )

    categories = {
        key: _path_list(payload, key) for key in MANIFEST_CATEGORIES
    }
    plan_paths = categories["plan_paths"]
    declared_epochs: set[int] = set()
    declared_plan_revisions: set[str] = set()
    for relative in plan_paths:
        try:
            text = (root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise Task11IndependentAuditError(
                "candidate manifest plan is invalid"
            ) from exc
        match = TASK11_EPOCH_PATTERN.search(text)
        if match is not None:
            declared_epochs.add(int(match.group(1)))
        plan_revision_match = PLAN_REVISION_PATTERN.search(text)
        if plan_revision_match is not None:
            declared_plan_revisions.add(plan_revision_match.group(1))
    _require(
        declared_epochs == {repair_epoch},
        "candidate manifest repair epoch does not match plan",
    )
    _require(
        declared_plan_revisions == {payload.get("plan_revision")},
        "candidate manifest plan revision does not match plan",
    )
    flattened = [
        relative
        for key in MANIFEST_CATEGORIES
        for relative in categories[key]
    ]
    _require(
        len(flattened) == len(set(flattened)),
        "candidate manifest typed path categories overlap",
    )
    protected = _path_list(payload, "protected_paths")
    _require(
        protected == sorted(flattened),
        "candidate manifest protected paths are not the exact typed union",
    )
    _require_local_static_dependencies(
        root=root,
        protected_paths=protected,
    )
    deleted = _path_list(payload, "deleted_paths")
    _require(
        set(protected).isdisjoint(deleted),
        "candidate manifest deleted paths overlap protected paths",
    )
    change_paths = _path_list(payload, "change_paths")
    _require(
        set(change_paths) <= {*protected, *deleted}
        and set(deleted) <= set(change_paths),
        "candidate manifest change paths are outside the protected set",
    )
    mutable = _path_list(payload, "mutable_evidence_paths")
    _require(
        len(mutable) == 1
        and PurePosixPath(mutable[0]).name == "smoke-attempt-ledger.json",
        "candidate manifest mutable evidence paths are invalid",
    )
    runtime_private_key_paths = payload.get(
        "fixture_runtime_private_key_paths"
    )
    _require(
        isinstance(runtime_private_key_paths, list)
        and len(runtime_private_key_paths) == 2
        and all(
            isinstance(value, str) and Path(value).is_absolute()
            for value in runtime_private_key_paths
        ),
        "candidate manifest runtime private key paths are invalid",
    )
    primary_key_path = Path(str(runtime_private_key_paths[0]))
    expected_retry_path = primary_key_path.with_name(
        f"{primary_key_path.stem}.retry-2{primary_key_path.suffix}"
    )
    _require(
        tuple(
            str(Path(value).parent.resolve() / Path(value).name)
            for value in runtime_private_key_paths
        )
        == (
            str(primary_key_path),
            str(expected_retry_path),
        )
        and all(
            not Path(value).is_relative_to(root)
            for value in runtime_private_key_paths
        ),
        "candidate manifest runtime private key paths are invalid",
    )
    ledger_path = (root / mutable[0]).resolve()
    ledger_binding = payload.get("pre_checkpoint_ledger")
    _require(
        isinstance(ledger_binding, dict)
        and set(ledger_binding)
        == {"path", "sha256", "revision", "revision_hash"}
        and ledger_binding.get("path") == str(ledger_path)
        and _is_digest(ledger_binding.get("sha256"))
        and isinstance(ledger_binding.get("revision"), int)
        and not isinstance(ledger_binding.get("revision"), bool)
        and int(ledger_binding["revision"]) >= 0
        and _is_digest(ledger_binding.get("revision_hash")),
        "candidate manifest pre-checkpoint ledger is invalid",
    )
    ledger_bytes = _read_regular_file_once(
        ledger_path,
        label="pre-checkpoint ledger",
    )
    try:
        ledger_payload = json.loads(ledger_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Task11IndependentAuditError(
            "pre-checkpoint ledger is invalid"
        ) from exc
    ledger_chain = (
        ledger_payload.get("revision_chain")
        if isinstance(ledger_payload, dict)
        else None
    )
    ledger_tip = (
        ledger_chain[-1]
        if isinstance(ledger_chain, list) and ledger_chain
        else None
    )
    _require(
        sha256(ledger_bytes).hexdigest()
        == ledger_binding["sha256"]
        and isinstance(ledger_tip, dict)
        and ledger_payload.get("revision")
        == ledger_binding["revision"]
        and ledger_tip.get("revision")
        == ledger_binding["revision"]
        and ledger_tip.get("revision_hash")
        == ledger_binding["revision_hash"],
        "candidate manifest pre-checkpoint ledger binding drift",
    )
    excluded = _excluded_patterns(payload)

    deleted_hashes = payload.get("deleted_base_blob_sha256_by_path")
    _require(
        isinstance(deleted_hashes, dict)
        and set(deleted_hashes) == set(deleted),
        "candidate manifest deleted blob hashes are invalid",
    )
    for relative in deleted:
        _require(
            not (root / relative).exists()
            and not (root / relative).is_symlink(),
            f"deleted path still exists: {relative}",
        )
        base = _git_blob(root, candidate_head, relative)
        _require(base is not None, f"deleted base blob is missing: {relative}")
        _require(
            deleted_hashes.get(relative) == sha256(base).hexdigest(),
            f"deleted base blob hash mismatch: {relative}",
        )

    current_payload_hash = _canonical_payload_hash(root, protected)
    _require(
        payload.get("candidate_payload_sha256") == current_payload_hash
        and payload.get("protected_payload_sha256")
        == current_payload_hash,
        "candidate manifest protected payload hash mismatch",
    )

    changed = _changed_paths(root, candidate_head)
    relevant_changed = {
        relative
        for relative in changed
        if _is_relevant_change_path(relative)
        and relative not in mutable
        and not _excluded(relative, excluded)
    }
    _require(
        relevant_changed == set(change_paths),
        "candidate manifest does not match the production diff",
    )
    diff_hash = _production_diff_hash(
        root=root,
        revision=candidate_head,
        change_paths=change_paths,
    )
    _require(
        path.parent.name.startswith("repair-epoch-"),
        "candidate manifest is not epoch-owned",
    )
    return current_payload_hash, diff_hash


def _semantic_responsibility(row: Mapping[str, object]) -> str:
    family = row.get("family")
    execution = row.get("execution")
    translation = row.get("translation")
    _require(
        isinstance(family, str)
        and isinstance(execution, dict)
        and isinstance(translation, dict),
        "semantic fixture row is invalid",
    )
    expected_mode = execution.get("expected_task_mode")
    operations = translation.get("allowed_operation_hints")
    _require(
        isinstance(operations, list)
        and all(isinstance(item, str) for item in operations),
        "semantic fixture operations are invalid",
    )
    if family == "recommendation":
        return "recommendation"
    if family == "followup" and expected_mode == "recommend":
        return "recommendation"
    if family != "image":
        return family
    if "image_identity" in operations:
        return "image_identity"
    if "comparison" in operations:
        return "comparison"
    if any(
        operation in {"knowledge", "followup"}
        for operation in operations
    ):
        return "product_knowledge"
    return "image_recommendation"


def _derive_semantic_summary(cases_path: Path) -> dict[str, object]:
    try:
        raw = cases_path.read_bytes()
        rows = [
            json.loads(line)
            for line in raw.decode("utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Task11IndependentAuditError(
            "semantic fixture is invalid"
        ) from exc
    _require(
        len(rows) == 128
        and all(isinstance(row, dict) for row in rows),
        "semantic fixture must contain 128 object rows",
    )
    case_ids = [row.get("case_id") for row in rows]
    _require(
        all(isinstance(case_id, str) and case_id for case_id in case_ids)
        and len(case_ids) == len(set(case_ids)),
        "semantic fixture case IDs are invalid",
    )
    recommendation_rows = [
        row
        for row in rows
        if _semantic_responsibility(row)
        in {"recommendation", "image_recommendation"}
    ]
    fit_count = 0
    explore_count = 0
    image_fit_count = 0
    missing_outcomes = 0
    cross_parent = 0
    explore_bases = {
        "broad_exploration",
        "bounded_exploration",
        "count_requested",
        "similar_alternatives",
    }
    fit_bases = {
        "single_best_request",
        "personal_suitability",
        "profile_match_choice",
        "best_among_candidates",
    }
    for row in recommendation_rows:
        execution = row.get("execution")
        _require(
            isinstance(execution, dict),
            "semantic fixture execution is invalid",
        )
        mode = execution.get("expected_recommendation_mode")
        basis = execution.get("expected_recommendation_mode_basis")
        if mode is None or basis is None:
            missing_outcomes += 1
            continue
        if mode == "fit":
            fit_count += 1
            cross_parent += basis not in fit_bases
            image_fit_count += (
                _semantic_responsibility(row)
                == "image_recommendation"
            )
        elif mode == "explore":
            explore_count += 1
            cross_parent += basis not in explore_bases
        else:
            missing_outcomes += 1
    return {
        "schema_version": "guide-task11-semantic-summary-v1",
        "matrix_kind": "expected_contract",
        "cases_sha256": sha256(raw).hexdigest(),
        "passed": (
            len(rows) == 128
            and explore_count > 0
            and missing_outcomes == 0
            and cross_parent == 0
        ),
        "case_count": len(rows),
        "fit_count": fit_count,
        "explore_count": explore_count,
        "image_fit_count": image_fit_count,
        "recommendation_outcome_contract_gap_count": missing_outcomes,
        "cross_parent_basis_count": cross_parent,
    }


def _validate_semantic_summary(
    payload: Mapping[str, object],
    *,
    cases_path: Path,
) -> None:
    label = "semantic summary"
    _require(
        dict(payload) == _derive_semantic_summary(cases_path),
        f"{label} does not match the protected semantic fixture",
    )


def _validate_network_report(
    payload: Mapping[str, object],
    *,
    runtime: bool,
    candidate_manifest_hash: str | None = None,
) -> str | None:
    label = "runtime network report" if runtime else "network report"
    expected_schema = (
        "guide-zero-api-runtime-network-report-v2"
        if runtime
        else "guide-zero-api-network-report-v1"
    )
    _require(
        payload.get("schema_version") == expected_schema,
        f"{label} schema is invalid",
    )
    _require(
        payload.get("guard_active") is True
        and payload.get("passed") is True,
        f"{label} is not passing under an active guard",
    )
    _required_zero(payload, "provider_call_count", label=label)
    _required_zero(payload, "outbound_network_attempt_count", label=label)
    _require(payload.get("attempts") == [], f"{label} attempts are not empty")
    _require(
        payload.get("process_guard_active") is True,
        f"{label} process guard is not active",
    )
    expected_process_policy = (
        "deny_process_creation"
        if runtime
        else "kernel_inherited_network_deny"
    )
    _require(
        payload.get("kernel_network_sandbox_active") is True
        and payload.get("child_process_policy")
        == expected_process_policy,
        f"{label} process guard kernel policy is invalid",
    )
    _required_zero(payload, "process_creation_attempt_count", label=label)
    _require(
        payload.get("process_creation_attempts") == [],
        f"{label} process attempts are not empty",
    )
    if not runtime:
        return None
    _require(
        payload.get("runtime_started") is True
        and payload.get("ready_identity_written") is True
        and payload.get("challenge_consumed") is True
        and payload.get("shutdown_consumed") is True
        and payload.get("shutdown_finalized") is True
        and payload.get("runtime_succeeded") is True,
        "runtime network report lifecycle is incomplete",
    )
    _require(
        candidate_manifest_hash is not None
        and payload.get("candidate_manifest_sha256")
        == candidate_manifest_hash,
        "runtime network report manifest hash mismatch",
    )
    runtime_identity_hash = payload.get("runtime_identity_sha256")
    consumed_challenge_sha256s = payload.get(
        "consumed_health_challenge_sha256s"
    )
    _require(
        _is_digest(runtime_identity_hash)
        and isinstance(consumed_challenge_sha256s, list)
        and bool(consumed_challenge_sha256s)
        and len(consumed_challenge_sha256s)
        == len(set(consumed_challenge_sha256s))
        and all(
            _is_digest(value)
            for value in consumed_challenge_sha256s
        ),
        "runtime network report provenance is invalid",
    )
    _validate_runtime_seatbelt_report(payload, label=label)
    return str(runtime_identity_hash)


def _validate_runtime_seatbelt_report(
    payload: Mapping[str, object],
    *,
    label: str,
) -> None:
    nonce = payload.get("measurement_nonce")
    profile = payload.get("sandbox_profile")
    runtime_profile = payload.get("runtime_sandbox_profile")
    raw_text = payload.get("seatbelt_raw_ndjson")
    _require(
        payload.get("measurement")
        == "macos-unified-log-seatbelt-kernel"
        and payload.get("process_group_quiescent") is True
        and payload.get("canary_process_groups_quiescent") is True
        and isinstance(nonce, str)
        and HEX_64.fullmatch(nonce) is not None
        and isinstance(profile, str)
        and isinstance(runtime_profile, str)
        and isinstance(raw_text, str),
        f"{label} Seatbelt measurement is invalid",
    )
    expected_profile = (
        "(version 1)"
        "(allow default)"
        "(deny network-outbound "
        "(with telemetry) "
        f"(with message \"{nonce}\"))"
        "(allow network-outbound (remote ip \"localhost:*\"))"
        "(allow network-inbound)"
    )
    profile_hash = sha256(profile.encode("utf-8")).hexdigest()
    expected_runtime_profile = (
        expected_profile
        + "(deny process-fork "
        "(with telemetry) "
        f"(with message \"{nonce}\"))"
    )
    runtime_profile_hash = sha256(
        runtime_profile.encode("utf-8")
    ).hexdigest()
    raw = raw_text.encode("utf-8")
    _require(
        profile == expected_profile
        and payload.get("sandbox_profile_sha256") == profile_hash
        and payload.get("sandbox_identity")
        == f"macos-sandbox-exec-loopback-only:{profile_hash}"
        and runtime_profile == expected_runtime_profile
        and payload.get("runtime_sandbox_profile_sha256")
        == runtime_profile_hash
        and payload.get("runtime_sandbox_identity")
        == (
            "macos-sandbox-exec-loopback-only-no-fork:"
            f"{runtime_profile_hash}"
        ),
        f"{label} Seatbelt profile binding is invalid",
    )
    _require(
        payload.get("seatbelt_raw_ndjson_sha256")
        == sha256(raw).hexdigest()
        and payload.get("seatbelt_raw_byte_count") == len(raw)
        and payload.get("logger_ready") is True
        and payload.get("logger_loss_event_count") == 0
        and payload.get("logger_returncode") in {0, 130, -2},
        f"{label} Seatbelt raw evidence is invalid",
    )
    events: list[dict[str, object]] = []
    try:
        for line in raw_text.splitlines():
            if not line:
                continue
            event = json.loads(line)
            _require(
                isinstance(event, dict),
                f"{label} Seatbelt raw event is invalid",
            )
            events.append(event)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Task11IndependentAuditError(
            f"{label} Seatbelt raw log is malformed"
        ) from exc
    _require(
        payload.get("seatbelt_event_count") == len(events)
        and not any(
            event.get("eventType") == "lossEvent"
            for event in events
        ),
        f"{label} Seatbelt logger lost events",
    )

    ready_marker = f"XIAORO_RUNTIME_SEATBELT_READY:{nonce}"
    drain_marker = f"XIAORO_RUNTIME_SEATBELT_DRAIN:{nonce}"
    canary_begin_pattern = re.compile(
        rf"^XIAORO_RUNTIME_SEATBELT_CANARY_BEGIN:{nonce}:(\d+)$"
    )
    canary_end_pattern = re.compile(
        rf"^XIAORO_RUNTIME_SEATBELT_CANARY_END:{nonce}:(\d+)$"
    )
    begin_pattern = re.compile(
        rf"^XIAORO_RUNTIME_SEATBELT_BEGIN:{nonce}:(\d+)$"
    )
    root_child_pattern = re.compile(
        rf"^XIAORO_RUNTIME_SEATBELT_CANARY:{nonce}:"
        r"root_child:(\d+):9$"
    )
    descendant_pattern = re.compile(
        rf"^XIAORO_RUNTIME_SEATBELT_CANARY:{nonce}:"
        r"descendant:(\d+):443$"
    )
    end_pattern = re.compile(
        rf"^XIAORO_RUNTIME_SEATBELT_END:{nonce}:(\d+)$"
    )
    drain_canary_pattern = re.compile(
        rf"^XIAORO_RUNTIME_SEATBELT_CANARY:{nonce}:"
        r"drain:(\d+):53$"
    )

    def markers(
        pattern: str | re.Pattern[str],
    ) -> list[tuple[int, re.Match[str] | None]]:
        found: list[tuple[int, re.Match[str] | None]] = []
        for index, event in enumerate(events):
            if event.get("processImagePath") != "/usr/bin/logger":
                continue
            message = event.get("eventMessage")
            if not isinstance(message, str):
                continue
            if isinstance(pattern, str):
                if message == pattern:
                    found.append((index, None))
                continue
            match = pattern.fullmatch(message)
            if match is not None:
                found.append((index, match))
        return found

    ready = markers(ready_marker)
    canary_begin = markers(canary_begin_pattern)
    begin = markers(begin_pattern)
    root_child = markers(root_child_pattern)
    descendant = markers(descendant_pattern)
    end = markers(end_pattern)
    canary_end = markers(canary_end_pattern)
    drain_canary = markers(drain_canary_pattern)
    drain = markers(drain_marker)
    _require(
        ready
        and len(canary_begin) == 1
        and len(canary_end) == 1
        and len(begin) == len(root_child) == len(descendant) == len(end) == 1
        and len(drain_canary) == 1
        and len(drain) == 1
        and payload.get("logger_readiness_marker_count") == len(ready)
        and payload.get("logger_drain_marker_count") == len(drain),
        f"{label} Seatbelt marker inventory is invalid",
    )
    begin_match = begin[0][1]
    root_child_match = root_child[0][1]
    descendant_match = descendant[0][1]
    end_match = end[0][1]
    canary_begin_match = canary_begin[0][1]
    canary_end_match = canary_end[0][1]
    drain_canary_match = drain_canary[0][1]
    _require(
        begin_match is not None
        and root_child_match is not None
        and descendant_match is not None
        and end_match is not None
        and canary_begin_match is not None
        and canary_end_match is not None
        and drain_canary_match is not None,
        f"{label} Seatbelt marker identity is invalid",
    )
    root_pid = int(begin_match.group(1))
    canary_root_pid = int(canary_begin_match.group(1))
    root_child_pid = int(root_child_match.group(1))
    descendant_pid = int(descendant_match.group(1))
    drain_canary_pid = int(drain_canary_match.group(1))
    _require(
        root_pid == int(end_match.group(1))
        and canary_root_pid == int(canary_end_match.group(1))
        and len({
            canary_root_pid,
            root_child_pid,
            descendant_pid,
            root_pid,
            drain_canary_pid,
        }) == 5
        and ready[0][0]
        < canary_begin[0][0]
        < root_child[0][0]
        < descendant[0][0]
        < canary_end[0][0]
        < begin[0][0]
        < end[0][0]
        < drain_canary[0][0]
        < drain[0][0]
        and payload.get("canary_root_pid") == canary_root_pid
        and payload.get("root_pid") == root_pid
        and payload.get("runtime_root_pid") == root_pid
        and payload.get("runtime_process_group_id") == root_pid
        and payload.get("drain_canary_pid") == drain_canary_pid
        and payload.get("root_child_canary_pid") == root_child_pid
        and payload.get("descendant_canary_pid") == descendant_pid,
        f"{label} Seatbelt marker order or PID is invalid",
    )

    denial_pattern = re.compile(
        r"^Sandbox: (?P<process>.+)\((?P<pid>\d+)\) deny\(1\) "
        r"network-outbound remote:\*:(?P<port>\d+)\n"
        rf"{nonce}$"
    )
    denials: list[dict[str, object]] = []
    for line_number, event in enumerate(events, start=1):
        if (
            event.get("processImagePath") != "/kernel"
            or event.get("senderImagePath")
            != (
                "/System/Library/Extensions/Sandbox.kext/"
                "Contents/MacOS/Sandbox"
            )
        ):
            continue
        message = event.get("eventMessage")
        if not isinstance(message, str):
            continue
        match = denial_pattern.fullmatch(message)
        _require(
            match is not None or nonce not in message,
            f"{label} Seatbelt denial event is malformed",
        )
        if match is not None:
            denials.append({
                "process": match.group("process"),
                "pid": int(match.group("pid")),
                "port": int(match.group("port")),
                "line_number": line_number,
            })
    root_denials = [
        item
        for item in denials
        if item["pid"] == root_child_pid and item["port"] == 9
    ]
    descendant_denials = [
        item
        for item in denials
        if item["pid"] == descendant_pid and item["port"] == 443
    ]
    drain_denials = [
        item
        for item in denials
        if item["pid"] == drain_canary_pid and item["port"] == 53
    ]
    _require(
        len(root_denials) == 1
        and len(descendant_denials) == 1
        and len(drain_denials) == 1,
        f"{label} Seatbelt canary evidence is invalid",
    )
    root_denial_index = int(root_denials[0]["line_number"]) - 1
    descendant_denial_index = (
        int(descendant_denials[0]["line_number"]) - 1
    )
    drain_denial_index = int(drain_denials[0]["line_number"]) - 1
    _require(
        canary_begin[0][0]
        < root_denial_index
        < descendant_denial_index
        < root_child[0][0]
        < descendant[0][0]
        < canary_end[0][0]
        and drain_canary[0][0]
        < drain_denial_index
        < drain[0][0],
        f"{label} Seatbelt canary delivery order is invalid",
    )
    canary_lines = {
        root_denials[0]["line_number"],
        descendant_denials[0]["line_number"],
        drain_denials[0]["line_number"],
    }
    process_tree_attempts = [
        item
        for item in denials
        if item["line_number"] not in canary_lines
    ]
    _require(
        payload.get("seatbelt_canary_denial_count") == 3
        and payload.get("canary_denials")
        == [
            root_denials[0],
            descendant_denials[0],
            drain_denials[0],
        ]
        and payload.get("process_tree_attempts") == process_tree_attempts
        and payload.get(
            "runtime_process_tree_non_loopback_attempt_count"
        )
        == len(process_tree_attempts)
        == 0,
        f"{label} Seatbelt process-tree evidence failed",
    )


def _validate_zero_api_summary(
    payload: Mapping[str, object],
    *,
    manifest: Mapping[str, object],
    manifest_sha256: str,
    protected_payload_hash: str,
    network_report_sha256: str,
) -> int:
    label = "zero API summary"
    _require(
        payload.get("schema_version")
        == "guide-task11-zero-api-summary-v1",
        f"{label} schema is invalid",
    )
    _require(
        payload.get("passed") is True
        and payload.get("guard_active") is True
        and payload.get("process_guard_active") is True
        and payload.get("kernel_network_sandbox_active") is True
        and payload.get("child_process_policy")
        == "kernel_inherited_network_deny",
        f"{label} is not passing under an active guard",
    )
    _required_zero(payload, "provider_call_count", label=label)
    _required_zero(payload, "outbound_network_attempt_count", label=label)
    _required_zero(payload, "process_creation_attempt_count", label=label)
    _require(
        payload.get("process_creation_attempts") == [],
        "zero API summary process attempts are not empty",
    )
    _require(
        payload.get("candidate_manifest_sha256")
        == manifest_sha256,
        "zero API summary manifest hash mismatch",
    )
    _require(
        payload.get("protected_payload_sha256") == protected_payload_hash,
        "zero API summary protected payload hash mismatch",
    )
    _require(
        payload.get("network_report_sha256") == network_report_sha256,
        "zero API summary network report hash mismatch",
    )
    commands = payload.get("commands")
    _require(
        isinstance(commands, list) and len(commands) == 3,
        "zero API summary commands are missing",
    )
    test_paths = manifest.get("test_paths")
    _require(
        isinstance(test_paths, list),
        "zero API summary manifest test paths are invalid",
    )
    expected_argv = (
        ["git", "diff", "--check"],
        [sys.executable, "-m", "compileall", "-q", "app", "tools", "tests"],
        [
            "/usr/bin/sandbox-exec",
            "-p",
            ZERO_API_SANDBOX_PROFILE,
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "tools.guide_gates.zero_api_network_guard",
            *[
                path
                for path in test_paths
                if isinstance(path, str) and path.endswith(".py")
            ],
        ],
    )
    for command, argv in zip(commands, expected_argv, strict=True):
        _require(
            isinstance(command, dict)
            and command.get("returncode") == 0
            and command.get("argv") == argv
            and isinstance(command.get("stdout"), str)
            and isinstance(command.get("stderr"), str),
            "zero API summary command evidence is invalid",
        )
    pytest_match = re.search(
        r"(?m)^(\d+) passed(?:,| in )",
        str(commands[-1]["stdout"]),
    )
    _require(
        pytest_match is not None,
        "zero API summary pytest count is invalid",
    )
    return int(pytest_match.group(1))


def _validate_architecture(
    payload: Mapping[str, object],
    *,
    manifest: Mapping[str, object],
    protected_payload_hash: str,
) -> None:
    label = "single-path architecture"
    modules = payload.get("inspected_modules")
    violations = payload.get("violations")
    _require(
        payload.get("schema_version")
        == "guide-task11-single-path-architecture-v1",
        f"{label} schema is invalid",
    )
    _require(payload.get("passed") is True, f"{label} did not pass")
    _require(
        isinstance(modules, list)
        and bool(modules)
        and len(modules) == len(set(modules))
        and all(isinstance(item, str) and item for item in modules),
        f"{label} inspected module inventory is invalid",
    )
    _require(
        _required_int(payload, "inspected_module_count", label=label)
        == len(modules),
        f"{label} inspected module count is inconsistent",
    )
    _require(
        violations == []
        and _required_int(payload, "violation_count", label=label) == 0,
        f"{label} contains violations",
    )
    if "forbidden_symbol_count" in payload:
        _required_zero(payload, "forbidden_symbol_count", label=label)
    if "protected_payload_sha256" in payload:
        _require(
            payload.get("protected_payload_sha256")
            == protected_payload_hash,
            f"{label} protected payload hash mismatch",
        )
    source_paths = manifest.get("source_paths")
    _require(isinstance(source_paths, list), "manifest source paths are invalid")
    expected_modules = {
        str(path)[:-3].replace("/", ".")
        for path in source_paths
        if isinstance(path, str)
        and path.startswith("app/")
        and path.endswith(".py")
        and not path.endswith("/__init__.py")
    }
    _require(
        expected_modules <= set(modules),
        f"{label} omitted a protected production module",
    )


def _call_name(node: ast.Call | ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        parts = [target.attr]
        value = target.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def _tool_tree(root: Path, relative: str) -> ast.Module:
    path = root / relative
    _require(
        path.is_file() and not path.is_symlink(),
        f"Task 12 execution file is missing or invalid: {relative}",
    )
    try:
        return ast.parse(
            path.read_text(encoding="utf-8"),
            filename=relative,
        )
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise Task11IndependentAuditError(
            f"Task 12 execution source is invalid: {relative}"
        ) from exc


def _tool_functions(
    tree: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _module_callable_assignments(
    tree: ast.Module,
) -> dict[str, tuple[tuple[tuple[int, int], ast.expr], ...]]:
    assignments: dict[
        str,
        list[tuple[tuple[int, int], ast.expr]],
    ] = {}
    for statement in tree.body:
        targets: Sequence[ast.expr]
        value: ast.expr | None
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = (statement.target,)
            value = statement.value
        else:
            continue
        if value is None:
            continue
        position = (statement.lineno, statement.col_offset)
        for target in targets:
            if isinstance(target, ast.Name):
                assignments.setdefault(target.id, []).append(
                    (position, value)
                )
    return {
        name: tuple(values)
        for name, values in assignments.items()
    }


def _validate_fixture_marker_ownership(root: Path) -> None:
    relative = "tools/guide_gates/run_mainline_contract_browser_audit.py"
    tree = _tool_tree(root, relative)
    functions = _tool_functions(tree)
    required_functions = {
        "_run_seatbelt_canary_child",
        "_run_seatbelt_canaries",
        "_run_fixture_drain_canary",
        "_execute_fixture_sandbox_process",
        "main",
    }
    _require(
        required_functions <= set(functions),
        "fixture parent-owned marker functions are missing",
    )

    known_false_names = _module_type_checking_aliases(tree)
    known_false_attributes = _module_type_checking_attributes(tree)
    module_assignments = _module_callable_assignments(tree)

    def executable_calls(
        function_name: str,
    ) -> tuple[
        tuple[ast.Call, frozenset[str], frozenset[str]],
        ...,
    ]:
        function = functions[function_name]
        local_bindings = _function_local_bindings(function)
        assignments: dict[
            str,
            list[tuple[tuple[int, int], ast.expr]],
        ] = {}

        def record_assignment(statement: ast.stmt) -> None:
            targets: Sequence[ast.expr]
            value: ast.expr | None
            if isinstance(statement, ast.Assign):
                targets = statement.targets
                value = statement.value
            elif isinstance(statement, ast.AnnAssign):
                targets = (statement.target,)
                value = statement.value
            else:
                return
            if value is None:
                return
            position = (statement.lineno, statement.col_offset)
            for target in targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(
                        (position, value)
                    )

        calls = _executable_call_nodes(
            function,
            include_local_names=True,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
            statement_visitor=record_assignment,
        )
        return tuple(
            (
                call,
                *_resolve_local_callable_targets(
                    call.func,
                    assignments=assignments,
                    module_assignments=module_assignments,
                    local_bindings=local_bindings,
                    module_function_names=functions,
                    before=(call.lineno, call.col_offset),
                ),
            )
            for call in calls
        )

    for root_name in (
        "_run_seatbelt_canary_child",
        "_run_seatbelt_canary_branch",
        "_run_seatbelt_canaries",
    ):
        reachable = {root_name}
        pending = [root_name]
        while pending:
            current = pending.pop()
            for _, possible_targets, _ in executable_calls(current):
                for resolved_target in possible_targets:
                    target = resolved_target.split(".")[-1]
                    if target in functions and target not in reachable:
                        reachable.add(target)
                        pending.append(target)
        _require(
            "_emit_seatbelt_marker" not in reachable,
            "fixture short-lived canary emits a marker",
        )
    capture = functions["_execute_fixture_sandbox_process"]
    capture_calls = executable_calls(
        "_execute_fixture_sandbox_process"
    )
    emit_count = sum(
        definite_targets == frozenset({"_emit_seatbelt_marker"})
        for _, _, definite_targets in capture_calls
    )
    wait_count = sum(
        definite_targets
        == frozenset({"_wait_for_fixture_marker_delivery"})
        for _, _, definite_targets in capture_calls
    )
    gate_writes = {
        call.args[0].value
        for call, _, _ in capture_calls
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "write"
            and isinstance(call.func.value, ast.Attribute)
            and call.func.value.attr == "stdin"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, bytes)
        )
    }
    piped_child = any(
        definite_targets == frozenset({"subprocess.Popen"})
        and "subprocess" not in _function_local_bindings(capture)
        and any(
            keyword.arg == "stdin"
            and isinstance(keyword.value, ast.Attribute)
            and _call_name(keyword.value) == "subprocess.PIPE"
            for keyword in call.keywords
        )
        for call, _, definite_targets in capture_calls
    )
    _require(
        emit_count >= 6
        and wait_count >= 4
        and gate_writes == {b"1", b"2"}
        and piped_child,
        "fixture parent-owned marker capture is incomplete",
    )

    drain_calls = executable_calls("_run_fixture_drain_canary")
    on_started_lines = [
        call.lineno
        for call, _, definite_targets in drain_calls
        if definite_targets == frozenset({"on_started"})
    ]
    drain_write_lines = [
        call.lineno
        for call, _, _ in drain_calls
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "write"
            and isinstance(call.func.value, ast.Attribute)
            and call.func.value.attr == "stdin"
        )
    ]
    _require(
        len(on_started_lines) == 1
        and len(drain_write_lines) == 1
        and on_started_lines[0] < drain_write_lines[0],
        "fixture drain marker is not emitted before canary release",
    )

    main_calls = executable_calls("main")
    gate_stages = {
        keyword.value.value
        for call, _, definite_targets in main_calls
        if definite_targets
        == frozenset({"_require_fixture_canary_gate"})
        for keyword in call.keywords
        if (
            keyword.arg == "stage"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        )
    }
    _require(
        {"start", "completion", "drain"} <= gate_stages,
        "fixture canary stdin gates are incomplete",
    )


def _module_callable_bindings(tree: ast.Module) -> set[str]:
    callables: set[str] = set()
    invalid: set[str] = set()

    class ModuleBindingVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.names: set[str] = set()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.names.add(node.name)

        def visit_AsyncFunctionDef(
            self,
            node: ast.AsyncFunctionDef,
        ) -> None:
            self.names.add(node.name)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.names.add(node.name)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            del node

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                self.names.add(node.id)

        def visit_Import(self, node: ast.Import) -> None:
            self.names.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in node.names
            )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            self.names.update(
                alias.asname or alias.name
                for alias in node.names
            )

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if isinstance(node.name, str):
                self.names.add(node.name)
            if node.type is not None:
                self.visit(node.type)
            for statement in node.body:
                self.visit(statement)

        def visit_MatchAs(self, node: ast.MatchAs) -> None:
            if node.name is not None:
                self.names.add(node.name)
            if node.pattern is not None:
                self.visit(node.pattern)

        def visit_MatchStar(self, node: ast.MatchStar) -> None:
            if node.name is not None:
                self.names.add(node.name)

        def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
            if node.rest is not None:
                self.names.add(node.rest)
            self.generic_visit(node)

    for node in tree.body:
        names: set[str] = set()
        trusted = False
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            trusted = True
        elif isinstance(node, ast.Import):
            names.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in node.names
            )
            trusted = True
        elif isinstance(node, ast.ImportFrom):
            names.update(
                alias.asname or alias.name
                for alias in node.names
            )
            trusted = True
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else (node.target,)
            )
            names.update(
                item.id
                for target in targets
                for item in ast.walk(target)
                if isinstance(item, ast.Name)
            )
        else:
            visitor = ModuleBindingVisitor()
            visitor.visit(node)
            names.update(visitor.names)
        for name in names:
            if name in callables or not trusted:
                invalid.add(name)
            elif name not in invalid:
                callables.add(name)
    return callables - invalid


def _function_local_bindings(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    bindings = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    if function.args.vararg is not None:
        bindings.add(function.args.vararg.arg)
    if function.args.kwarg is not None:
        bindings.add(function.args.kwarg.arg)

    class BindingVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            bindings.add(node.name)

        def visit_AsyncFunctionDef(
            self,
            node: ast.AsyncFunctionDef,
        ) -> None:
            bindings.add(node.name)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            bindings.add(node.name)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            del node

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                bindings.add(node.id)

        def visit_Import(self, node: ast.Import) -> None:
            bindings.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in node.names
            )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            bindings.update(
                alias.asname or alias.name
                for alias in node.names
            )

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if isinstance(node.name, str):
                bindings.add(node.name)
            if node.type is not None:
                self.visit(node.type)
            for statement in node.body:
                self.visit(statement)

        def visit_MatchAs(self, node: ast.MatchAs) -> None:
            if node.name is not None:
                bindings.add(node.name)
            if node.pattern is not None:
                self.visit(node.pattern)

        def visit_MatchStar(self, node: ast.MatchStar) -> None:
            if node.name is not None:
                bindings.add(node.name)

        def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
            if node.rest is not None:
                bindings.add(node.rest)
            self.generic_visit(node)

    visitor = BindingVisitor()
    for statement in function.body:
        visitor.visit(statement)
    return bindings


def _resolve_local_callable_targets(
    node: ast.expr,
    *,
    assignments: Mapping[
        str,
        Sequence[tuple[tuple[int, int], ast.expr]],
    ],
    module_assignments: Mapping[
        str,
        Sequence[tuple[tuple[int, int], ast.expr]],
    ],
    local_bindings: Collection[str],
    module_function_names: Collection[str],
    before: tuple[int, int],
    seen: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[frozenset[str], frozenset[str]]:
    if not isinstance(node, ast.Name):
        name = _call_name(node)
        targets = frozenset({name}) if name else frozenset()
        return targets, targets
    local_identity = ("local", node.id)
    if local_identity in seen:
        return frozenset(), frozenset()
    prior_values = tuple(
        (position, value)
        for position, value in assignments.get(node.id, ())
        if position < before
    )
    if prior_values:
        possible_targets: set[str] = set()
        definite_candidates: list[frozenset[str]] = []
        for position, value in prior_values:
            possible, definite = _resolve_local_callable_targets(
                value,
                assignments=assignments,
                module_assignments=module_assignments,
                local_bindings=local_bindings,
                module_function_names=module_function_names,
                before=position,
                seen=seen | {local_identity},
            )
            possible_targets.update(possible)
            definite_candidates.append(definite)
        definite_targets = (
            definite_candidates[0]
            if (
                definite_candidates
                and len(definite_candidates[0]) == 1
                and all(
                    candidate == definite_candidates[0]
                    for candidate in definite_candidates[1:]
                )
            )
            else frozenset()
        )
        return frozenset(possible_targets), definite_targets
    if (
        node.id in local_bindings
        and (
            node.id in module_function_names
            or node.id in module_assignments
        )
    ):
        return frozenset(), frozenset()
    module_identity = ("module", node.id)
    module_values = module_assignments.get(node.id, ())
    if module_values and module_identity not in seen:
        possible_targets = set()
        definite_candidates = []
        for position, value in module_values:
            possible, definite = _resolve_local_callable_targets(
                value,
                assignments={},
                module_assignments=module_assignments,
                local_bindings=(),
                module_function_names=module_function_names,
                before=position,
                seen=seen | {module_identity},
            )
            possible_targets.update(possible)
            definite_candidates.append(definite)
        definite_targets = (
            definite_candidates[0]
            if (
                definite_candidates
                and len(definite_candidates[0]) == 1
                and all(
                    candidate == definite_candidates[0]
                    for candidate in definite_candidates[1:]
                )
            )
            else frozenset()
        )
        return frozenset(possible_targets), definite_targets
    targets = frozenset({node.id})
    return targets, targets


_UNKNOWN_STATIC_VALUE = object()


def _static_value(
    value: ast.expr,
    *,
    known_false_names: Collection[str],
    known_false_attributes: Collection[str],
) -> object:
    if isinstance(value, ast.Name) and value.id in known_false_names:
        return False
    if (
        isinstance(value, ast.Attribute)
        and _call_name(value) in known_false_attributes
    ):
        return False
    try:
        return ast.literal_eval(value)
    except (ValueError, TypeError):
        return _UNKNOWN_STATIC_VALUE


def _static_truth(
    value: ast.expr,
    *,
    known_false_names: Collection[str] = (),
    known_false_attributes: Collection[str] = (),
) -> bool | None:
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not):
        operand = _static_truth(
            value.operand,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
        return None if operand is None else not operand
    if isinstance(value, ast.BoolOp):
        truths = tuple(
            _static_truth(
                item,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            )
            for item in value.values
        )
        if isinstance(value.op, ast.And):
            if False in truths:
                return False
            return True if all(item is True for item in truths) else None
        if True in truths:
            return True
        return False if all(item is False for item in truths) else None
    if isinstance(value, ast.Compare):
        resolved = tuple(
            _static_value(
                item,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            )
            for item in (value.left, *value.comparators)
        )
        if _UNKNOWN_STATIC_VALUE in resolved:
            return None
        try:
            comparisons = tuple(
                (
                    left == right
                    if isinstance(operator, ast.Eq)
                    else left != right
                    if isinstance(operator, ast.NotEq)
                    else left < right
                    if isinstance(operator, ast.Lt)
                    else left <= right
                    if isinstance(operator, ast.LtE)
                    else left > right
                    if isinstance(operator, ast.Gt)
                    else left >= right
                    if isinstance(operator, ast.GtE)
                    else left is right
                    if isinstance(operator, ast.Is)
                    else left is not right
                    if isinstance(operator, ast.IsNot)
                    else left in right
                    if isinstance(operator, ast.In)
                    else left not in right
                    if isinstance(operator, ast.NotIn)
                    else _UNKNOWN_STATIC_VALUE
                )
                for left, operator, right in zip(
                    resolved[:-1],
                    value.ops,
                    resolved[1:],
                    strict=True,
                )
            )
        except (TypeError, ValueError):
            return None
        if _UNKNOWN_STATIC_VALUE in comparisons:
            return None
        return all(comparisons)
    resolved = _static_value(
        value,
        known_false_names=known_false_names,
        known_false_attributes=known_false_attributes,
    )
    return (
        None
        if resolved is _UNKNOWN_STATIC_VALUE
        else bool(resolved)
    )


def _static_iterable_is_empty(
    value: ast.expr,
    *,
    known_false_names: Collection[str] = (),
    known_false_attributes: Collection[str] = (),
) -> bool:
    resolved = _static_value(
        value,
        known_false_names=known_false_names,
        known_false_attributes=known_false_attributes,
    )
    if isinstance(
        resolved,
        (tuple, list, set, dict, str, bytes),
    ):
        return len(resolved) == 0
    return False


def _module_type_checking_aliases(tree: ast.Module) -> set[str]:
    candidates = {
        alias.asname or alias.name
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom)
        and statement.module == "typing"
        for alias in statement.names
        if alias.name == "TYPE_CHECKING"
    }
    rebound: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rebound.add(statement.name)
        elif isinstance(statement, ast.ClassDef):
            rebound.add(statement.name)
        elif isinstance(statement, ast.Assign):
            rebound.update(
                node.id
                for target in statement.targets
                for node in ast.walk(target)
                if isinstance(node, ast.Name)
            )
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
            rebound.update(
                node.id
                for node in ast.walk(statement.target)
                if isinstance(node, ast.Name)
            )
        elif isinstance(statement, ast.Import):
            rebound.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in statement.names
            )
        elif isinstance(statement, ast.ImportFrom):
            rebound.update(
                alias.asname or alias.name
                for alias in statement.names
                if not (
                    statement.module == "typing"
                    and alias.name == "TYPE_CHECKING"
                )
            )
    return candidates - rebound


def _module_type_checking_attributes(tree: ast.Module) -> set[str]:
    candidates = {
        f"{alias.asname or alias.name}.TYPE_CHECKING"
        for statement in tree.body
        if isinstance(statement, ast.Import)
        for alias in statement.names
        if alias.name == "typing"
    }
    rebound: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rebound.add(statement.name)
        elif isinstance(statement, ast.ClassDef):
            rebound.add(statement.name)
        elif isinstance(statement, ast.Assign):
            rebound.update(
                node.id
                for target in statement.targets
                for node in ast.walk(target)
                if isinstance(node, ast.Name)
            )
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
            rebound.update(
                node.id
                for node in ast.walk(statement.target)
                if isinstance(node, ast.Name)
            )
        elif isinstance(statement, ast.Import):
            rebound.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in statement.names
                if alias.name != "typing"
            )
        elif isinstance(statement, ast.ImportFrom):
            rebound.update(
                alias.asname or alias.name
                for alias in statement.names
            )
    return {
        candidate
        for candidate in candidates
        if candidate.split(".", 1)[0] not in rebound
    }


def _statements_guaranteed_to_terminate(
    statements: Sequence[ast.stmt],
    *,
    known_false_names: Collection[str],
    known_false_attributes: Collection[str],
) -> bool:
    return any(
        _statement_guaranteed_to_terminate(
            statement,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
        for statement in statements
    )


def _statement_guaranteed_to_terminate(
    statement: ast.stmt,
    *,
    known_false_names: Collection[str],
    known_false_attributes: Collection[str],
) -> bool:
    if isinstance(
        statement,
        (ast.Break, ast.Continue, ast.Raise, ast.Return),
    ):
        return True
    if isinstance(statement, ast.Assert):
        return (
            _static_truth(
                statement.test,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            )
            is False
        )
    if isinstance(statement, (ast.Try, ast.TryStar)):
        if _statements_guaranteed_to_terminate(
            statement.finalbody,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        ):
            return True
        normal_path_terminates = (
            _statements_guaranteed_to_terminate(
                statement.body,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            )
            or (
                bool(statement.orelse)
                and _statements_guaranteed_to_terminate(
                    statement.orelse,
                    known_false_names=known_false_names,
                    known_false_attributes=known_false_attributes,
                )
            )
        )
        exception_paths_terminate = (
            not statement.handlers
            or all(
                _statements_guaranteed_to_terminate(
                    handler.body,
                    known_false_names=known_false_names,
                    known_false_attributes=known_false_attributes,
                )
                for handler in statement.handlers
            )
        )
        return normal_path_terminates and exception_paths_terminate
    if not isinstance(statement, ast.If):
        return False
    truth = _static_truth(
        statement.test,
        known_false_names=known_false_names,
        known_false_attributes=known_false_attributes,
    )
    if truth is True:
        return _statements_guaranteed_to_terminate(
            statement.body,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
    if truth is False:
        return _statements_guaranteed_to_terminate(
            statement.orelse,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
    return bool(statement.orelse) and all(
        _statements_guaranteed_to_terminate(
            branch,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
        for branch in (statement.body, statement.orelse)
    )


def _executable_call_nodes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    include_local_names: bool = False,
    known_false_names: Collection[str] = (),
    known_false_attributes: Collection[str] = (),
    statement_visitor: Callable[[ast.stmt], None] | None = None,
) -> tuple[ast.Call, ...]:
    local_bindings = _function_local_bindings(function)
    calls: list[ast.Call] = []

    class ExecutableCallVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            del node

        def visit_AsyncFunctionDef(
            self,
            node: ast.AsyncFunctionDef,
        ) -> None:
            del node

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            del node

        def visit_Lambda(self, node: ast.Lambda) -> None:
            del node

        def visit_If(self, node: ast.If) -> None:
            truth = _static_truth(
                node.test,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            )
            self.visit(node.test)
            if truth is not False:
                self.visit_statements(node.body)
            if truth is not True:
                self.visit_statements(node.orelse)

        def visit_While(self, node: ast.While) -> None:
            truth = _static_truth(
                node.test,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            )
            self.visit(node.test)
            if truth is not False:
                self.visit_statements(node.body)
            self.visit_statements(node.orelse)

        def visit_For(self, node: ast.For) -> None:
            self.visit(node.target)
            self.visit(node.iter)
            if not _static_iterable_is_empty(
                node.iter,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            ):
                self.visit_statements(node.body)
            self.visit_statements(node.orelse)

        def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
            self.visit(node.target)
            self.visit(node.iter)
            if not _static_iterable_is_empty(
                node.iter,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            ):
                self.visit_statements(node.body)
            self.visit_statements(node.orelse)

        def visit_Try(self, node: ast.Try) -> None:
            self.visit_statements(node.body)
            for handler in node.handlers:
                if handler.type is not None:
                    self.visit(handler.type)
                self.visit_statements(handler.body)
            self.visit_statements(node.orelse)
            self.visit_statements(node.finalbody)

        def visit_ListComp(self, node: ast.ListComp) -> None:
            self.visit_comprehension(
                generators=node.generators,
                values=(node.elt,),
            )

        def visit_SetComp(self, node: ast.SetComp) -> None:
            self.visit_comprehension(
                generators=node.generators,
                values=(node.elt,),
            )

        def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
            self.visit_comprehension(
                generators=node.generators,
                values=(node.elt,),
            )

        def visit_DictComp(self, node: ast.DictComp) -> None:
            self.visit_comprehension(
                generators=node.generators,
                values=(node.key, node.value),
            )

        def visit_comprehension(
            self,
            *,
            generators: Sequence[ast.comprehension],
            values: Sequence[ast.expr],
        ) -> None:
            for generator in generators:
                self.visit(generator.iter)
                if _static_iterable_is_empty(
                    generator.iter,
                    known_false_names=known_false_names,
                    known_false_attributes=known_false_attributes,
                ):
                    return
                self.visit(generator.target)
                for condition in generator.ifs:
                    self.visit(condition)
                    if (
                        _static_truth(
                            condition,
                            known_false_names=known_false_names,
                            known_false_attributes=(
                                known_false_attributes
                            ),
                        )
                        is False
                    ):
                        return
            for value in values:
                self.visit(value)

        def visit_Call(self, node: ast.Call) -> None:
            if (
                isinstance(node.func, ast.Attribute)
                or (
                    isinstance(node.func, ast.Name)
                    and (
                        include_local_names
                        or node.func.id not in local_bindings
                    )
                )
            ):
                calls.append(node)
            self.generic_visit(node)

        def visit_statements(self, statements: Sequence[ast.stmt]) -> None:
            for statement in statements:
                if statement_visitor is not None:
                    statement_visitor(statement)
                self.visit(statement)
                if isinstance(
                    statement,
                    (ast.Break, ast.Continue, ast.Raise, ast.Return),
                ):
                    break
                if _statement_guaranteed_to_terminate(
                    statement,
                    known_false_names=known_false_names,
                    known_false_attributes=known_false_attributes,
                ):
                    break

    visitor = ExecutableCallVisitor()
    visitor.visit_statements(function.body)
    return tuple(calls)


def _function_call_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    known_false_names: Collection[str] = (),
    known_false_attributes: Collection[str] = (),
) -> tuple[str, ...]:
    return tuple(
        _call_name(node).rsplit(".", 1)[-1]
        for node in _executable_call_nodes(
            function,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
        if isinstance(node.func, ast.Name) and _call_name(node)
    )


def _function_strings(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    return {
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
    }


def _module_strings(tree: ast.Module) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
    }


def _class_field_names(tree: ast.Module, class_name: str) -> set[str]:
    classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    target = classes.get(class_name)
    _require(
        target is not None,
        f"Task 12 class is missing: {class_name}",
    )
    return {
        node.target.id
        for node in target.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
    }


def _required_cli_arguments(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    known_false_names: Collection[str] = (),
    known_false_attributes: Collection[str] = (),
) -> set[str]:
    required: set[str] = set()
    for call in _executable_call_nodes(
        function,
        known_false_names=known_false_names,
        known_false_attributes=known_false_attributes,
    ):
        if _call_name(call).rsplit(".", 1)[-1] != "add_argument":
            continue
        if (
            not call.args
            or not isinstance(call.args[0], ast.Constant)
            or not isinstance(call.args[0].value, str)
        ):
            continue
        if any(
            keyword.arg == "required"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in call.keywords
        ):
            required.add(call.args[0].value)
    return required


def _literal_subparser_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    known_false_names: Collection[str] = (),
    known_false_attributes: Collection[str] = (),
) -> set[str]:
    return {
        str(call.args[0].value)
        for call in _executable_call_nodes(
            function,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
        if _call_name(call).rsplit(".", 1)[-1] == "add_parser"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }


def _reachable_tool_calls(
    tree: ast.Module,
    *,
    entry: str,
) -> set[str]:
    functions = _tool_functions(tree)
    trusted_callables = _module_callable_bindings(tree)
    known_false_names = _module_type_checking_aliases(tree)
    known_false_attributes = _module_type_checking_attributes(tree)
    _require(entry in functions, f"Task 12 function is missing: {entry}")
    reached: set[str] = set()
    pending = [entry]
    while pending:
        current = pending.pop()
        if current in reached:
            continue
        reached.add(current)
        calls = tuple(
            call
            for call in _function_call_names(
                functions[current],
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            )
            if call in trusted_callables
        )
        for call in calls:
            if call in functions and call not in reached:
                pending.append(call)
            else:
                reached.add(call)
    return reached


def _require_tool_calls(
    tree: ast.Module,
    *,
    entry: str,
    required: Sequence[str],
    label: str,
) -> None:
    reached = _reachable_tool_calls(tree, entry=entry)
    missing = sorted(set(required) - reached)
    _require(
        not missing,
        f"{label} is missing required calls: {', '.join(missing)}",
    )


def _require_module_import(
    tree: ast.Module,
    *,
    imported_module: str,
    imported_symbol: str,
    label: str,
) -> None:
    aliases = [
        alias.asname or alias.name
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom)
        and statement.module == imported_module
        for alias in statement.names
        if alias.name == imported_symbol
    ]
    _require(
        aliases == [imported_symbol]
        and imported_symbol in _module_callable_bindings(tree),
        f"{label} import is invalid",
    )


def _function_rebound_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    imported_module: str,
    imported_symbol: str,
) -> set[str]:
    names = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    if function.args.vararg is not None:
        names.add(function.args.vararg.arg)
    if function.args.kwarg is not None:
        names.add(function.args.kwarg.arg)

    class RebindingVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            names.add(node.name)

        def visit_AsyncFunctionDef(
            self,
            node: ast.AsyncFunctionDef,
        ) -> None:
            names.add(node.name)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            names.add(node.name)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            del node

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                names.add(node.id)

        def visit_Import(self, node: ast.Import) -> None:
            names.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in node.names
            )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            names.update(
                alias.asname or alias.name
                for alias in node.names
                if not (
                    node.module == imported_module
                    and alias.name == imported_symbol
                )
            )

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if isinstance(node.name, str):
                names.add(node.name)
            if node.type is not None:
                self.visit(node.type)
            for statement in node.body:
                self.visit(statement)

        def visit_MatchAs(self, node: ast.MatchAs) -> None:
            if node.name is not None:
                names.add(node.name)
            if node.pattern is not None:
                self.visit(node.pattern)

        def visit_MatchStar(self, node: ast.MatchStar) -> None:
            if node.name is not None:
                names.add(node.name)

        def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
            if node.rest is not None:
                names.add(node.rest)
            self.generic_visit(node)

    visitor = RebindingVisitor()
    for statement in function.body:
        visitor.visit(statement)
    return names


def _require_local_imported_call(
    tree: ast.Module,
    *,
    entry: str,
    imported_module: str,
    imported_symbol: str,
    label: str,
) -> None:
    functions = _tool_functions(tree)
    function = functions.get(entry)
    _require(function is not None, f"{label} function is missing")
    aliases = {
        alias.asname or alias.name
        for statement in function.body
        if isinstance(statement, ast.ImportFrom)
        and statement.module == imported_module
        for alias in statement.names
        if alias.name == imported_symbol
    }
    rebound = _function_rebound_names(
        function,
        imported_module=imported_module,
        imported_symbol=imported_symbol,
    )
    direct_statements: list[ast.stmt] = []
    known_false_names = _module_type_checking_aliases(tree)
    known_false_attributes = _module_type_checking_attributes(tree)
    for statement in function.body:
        candidates = (
            statement.body
            if isinstance(statement, ast.Try)
            else (statement,)
        )
        for candidate in candidates:
            direct_statements.append(candidate)
            if _statement_guaranteed_to_terminate(
                candidate,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            ):
                break
        if _statement_guaranteed_to_terminate(
            statement,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        ):
            break
    calls = [
        statement.value
        for statement in direct_statements
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id in aliases
    ]
    exact_argument = (
        len(calls) == 1
        and not calls[0].keywords
        and len(calls[0].args) == 1
        and ast.unparse(calls[0].args[0])
        == "Path(str(output_directory))"
        and "Path" in _module_callable_bindings(tree)
    )
    _require(
        len(aliases) == 1
        and not aliases.intersection(rebound)
        and len(calls) == 1
        and exact_argument,
        f"{label} is missing required local imported call",
    )


def _require_cli_surface(
    tree: ast.Module,
    *,
    required_strings: Sequence[str],
    required_arguments: Sequence[str],
    label: str,
) -> None:
    functions = _tool_functions(tree)
    parser = functions.get("_parse_args") or functions.get("_parser")
    _require(parser is not None, f"{label} parser is missing")
    known_false_names = _module_type_checking_aliases(tree)
    known_false_attributes = _module_type_checking_attributes(tree)
    strings = _function_strings(parser)
    missing_strings = sorted(set(required_strings) - strings)
    missing_arguments = sorted(
        set(required_arguments)
        - _required_cli_arguments(
            parser,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
    )
    _require(
        not missing_strings,
        f"{label} CLI is missing: {', '.join(missing_strings)}",
    )
    _require(
        not missing_arguments,
        f"{label} required CLI arguments are missing: "
        + ", ".join(missing_arguments),
    )


def _require_call_order(
    tree: ast.Module,
    *,
    function_name: str,
    before: str,
    after: str,
    label: str,
) -> None:
    functions = _tool_functions(tree)
    function = functions.get(function_name)
    trusted_callables = _module_callable_bindings(tree)
    _require(
        function is not None,
        f"{label} function is missing: {function_name}",
    )
    lines: dict[str, list[int]] = {before: [], after: []}
    for call in _executable_call_nodes(
        function,
        known_false_names=_module_type_checking_aliases(tree),
        known_false_attributes=_module_type_checking_attributes(tree),
    ):
        name = _call_name(call).rsplit(".", 1)[-1]
        if name in lines and name in trusted_callables:
            lines[name].append(call.lineno)
    _require(
        len(lines[before]) == 1
        and len(lines[after]) == 1
        and lines[before][0] < lines[after][0],
        f"{label} readiness/authorization order is invalid",
    )


def _class_method(
    tree: ast.Module,
    *,
    class_name: str,
    method_name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        return next(
            (
                statement
                for statement in node.body
                if isinstance(
                    statement,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and statement.name == method_name
            ),
            None,
        )
    return None


def _validate_readiness_completion_source(tree: ast.Module) -> None:
    function = _tool_functions(tree).get("derive_candidate_readiness")
    _require(
        function is not None,
        "readiness completion fields function is missing",
    )
    readiness_dicts = [
        statement.value
        for statement in function.body
        if isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "readiness"
            for target in statement.targets
        )
        and isinstance(statement.value, ast.Dict)
    ]
    _require(
        len(readiness_dicts) == 1,
        "readiness completion fields are not uniquely defined",
    )
    fields = {
        key.value: value
        for key, value in zip(
            readiness_dicts[0].keys,
            readiness_dicts[0].values,
            strict=True,
        )
        if isinstance(key, ast.Constant)
        and isinstance(key.value, str)
    }
    _require(
        all(
            isinstance(fields.get(field), ast.Name)
            and fields[field].id == binding
            for field, binding in READINESS_COMPLETION_BINDINGS.items()
        ),
        "readiness completion fields are not evidence-derived",
    )

    build_audit = _tool_functions(tree).get("build_test_path_audit")
    _require(
        build_audit is not None,
        "test path audit builder is missing",
    )
    assignments = [
        node
        for node in ast.walk(build_audit)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ]
    _require(
        any(
            node.targets[0].id == "layers_executed"
            and isinstance(node.value, ast.Call)
            and _call_name(node.value) == "list"
            and len(node.value.args) == 1
            and isinstance(node.value.args[0], ast.Name)
            and node.value.args[0].id == "_RUNTIME_LAYER_ORDER"
            for node in assignments
        )
        and any(
            node.targets[0].id == "runtime_evidence_source"
            and isinstance(node.value, ast.Constant)
            and node.value.value == "task11-production-path-summary"
            for node in assignments
        ),
        "test path runtime evidence source is not fail-closed",
    )


def _validate_governance_source_contracts(
    *,
    root: Path,
    manifest: Mapping[str, object],
) -> None:
    tool_paths = manifest.get("tool_paths")
    _require(
        isinstance(tool_paths, list)
        and PRODUCTION_MATRIX_TOOL_PATH in tool_paths,
        "production matrix tool is not protected",
    )
    protected_paths = manifest.get("protected_paths")
    _require(
        isinstance(protected_paths, list)
        and set(BROWSER_CANONICAL_DATA_PATHS) <= set(protected_paths),
        "browser canonical data is absent from the protected manifest",
    )
    tree = _tool_tree(root, PRODUCTION_MATRIX_TOOL_PATH)
    execute = _class_method(
        tree,
        class_name="Task11ProductionPathRuntime",
        method_name="execute",
    )
    _require(
        execute is not None,
        "production matrix runtime execute is missing",
    )
    calls = [
        call
        for call in _executable_call_nodes(
            execute,
            known_false_names=_module_type_checking_aliases(tree),
            known_false_attributes=_module_type_checking_attributes(tree),
        )
        if _call_name(call).rsplit(".", 1)[-1]
        == "_derive_state_coverage"
    ]
    arguments = (
        {
            keyword.arg: ast.unparse(keyword.value)
            for keyword in calls[0].keywords
            if keyword.arg is not None
        }
        if len(calls) == 1
        else {}
    )
    _require(
        arguments
        == {
            "current": "before",
            "understanding": "self._observer.compiled_understanding",
            "decision": "self._observer.route_decision",
            "committed": "after",
            "current_image_action": "case.image_action",
        },
        "production coverage does not use observed compiler output",
    )
    observed_assignments = [
        node
        for node in ast.walk(execute)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "observed_layers"
    ]
    _require(
        len(observed_assignments) == 1
        and isinstance(observed_assignments[0].value, ast.Call)
        and _call_name(
            observed_assignments[0].value
        ).rsplit(".", 1)[-1]
        == "_derive_observed_layers",
        "production runtime layers are not derived from observations",
    )
    compiled = _class_method(
        tree,
        class_name="_ProductionPathObserver",
        method_name="compiled",
    )
    _require(
        compiled is not None
        and any(
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and ast.unparse(node.targets[0])
            == "self.compiled_understanding"
            and ast.unparse(node.value) == "values['understanding']"
            for node in ast.walk(compiled)
        ),
        "production observer does not retain observed compiler output",
    )

    source_paths = manifest.get("source_paths")
    if not isinstance(source_paths, list):
        return
    source_path_set = set(source_paths)
    router_path = "app/guide/intent/unified_turn_router.py"
    if router_path in source_path_set:
        router_tree = _tool_tree(root, router_path)
        router = _tool_functions(router_tree).get("route_unified_turn")
        router_task_defaults = (
            [
                default
                for argument, default in zip(
                    router.args.kwonlyargs,
                    router.args.kw_defaults,
                    strict=True,
                )
                if argument.arg == "task_plan"
            ]
            if router is not None
            else []
        )
        router_calls = (
            _executable_call_nodes(
                router,
                known_false_names=_module_type_checking_aliases(router_tree),
                known_false_attributes=(
                    _module_type_checking_attributes(router_tree)
                ),
            )
            if router is not None
            else ()
        )
        _require(
            router_task_defaults == [None]
            and all(
                _call_name(call).rsplit(".", 1)[-1] != "plan_task"
                for call in router_calls
            ),
            "Router task-plan authority is not pre-routing only",
        )

    inference_path = "app/guide/adapters/image/inference_limiter.py"
    if inference_path in source_path_set:
        inference_tree = _tool_tree(root, inference_path)
        inference_slot = _tool_functions(inference_tree).get(
            "image_inference_slot"
        )
        timeout_defaults = (
            [
                default
                for argument, default in zip(
                    inference_slot.args.kwonlyargs,
                    inference_slot.args.kw_defaults,
                    strict=True,
                )
                if argument.arg == "timeout"
            ]
            if inference_slot is not None
            else []
        )
        _require(
            len(timeout_defaults) == 1
            and isinstance(timeout_defaults[0], ast.Constant)
            and timeout_defaults[0].value == 0.0,
            "image inference admission can wait without a bound",
        )

    runtime_path = "app/guide_runtime/app.py"
    if runtime_path in source_path_set:
        runtime_tree = _tool_tree(root, runtime_path)
        fixture_routes = {
            node.value
            for function in ast.walk(runtime_tree)
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            for decorator in function.decorator_list
            if isinstance(decorator, ast.Call)
            for node in decorator.args[:1]
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.endswith("/guide-demo-fixture.js")
        }
        _require(
            not fixture_routes,
            "runtime publicly exposes fixture transport",
        )
    fixture_path = "app/static/guide-demo-fixture.js"
    if fixture_path in set(manifest.get("protected_paths", ())):
        fixture_source = _input_file(
            root / fixture_path,
            label="offline fixture transport",
        ).read_text(encoding="utf-8")
        _require(
            "['message'," not in fixture_source
            and '["message",' not in fixture_source,
            "offline fixture emits a forbidden legacy public event",
        )
    protected_processors = set(PROCESSOR_SOURCE_ROOTS) & set(
        source_paths
    )
    if not protected_processors:
        return
    _require(
        protected_processors == set(PROCESSOR_SOURCE_ROOTS)
        and UNIFIED_FLOW_SOURCE_PATH in source_paths,
        "concrete processor entry source inventory is incomplete",
    )
    for relative, (class_name, method_name) in (
        PROCESSOR_SOURCE_ROOTS.items()
    ):
        processor_tree = _tool_tree(root, relative)
        method = _class_method(
            processor_tree,
            class_name=class_name,
            method_name=method_name,
        )
        _require(
            method is not None,
            f"concrete processor entry is missing: {class_name}.{method_name}",
        )
        calls = [
            call
            for call in _executable_call_nodes(
                method,
                known_false_names=(
                    _module_type_checking_aliases(processor_tree)
                ),
                known_false_attributes=(
                    _module_type_checking_attributes(processor_tree)
                ),
            )
            if _call_name(call).rsplit(".", 1)[-1]
            == "notify_processor_entry"
        ]
        direct_calls = [
            statement.value
            for statement in method.body
            if isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and statement.value in calls
        ]
        keywords = (
            {
                keyword.arg: ast.unparse(keyword.value)
                for keyword in calls[0].keywords
                if keyword.arg is not None
            }
            if len(calls) == 1
            else {}
        )
        _require(
            len(calls) == 1
            and len(direct_calls) == 1
            and keywords.get("execution_input") == "execution_input"
            and keywords.get("implementation")
            == "type(self).__qualname__"
            and keywords.get("processor_instance") == "self",
            f"concrete processor entry is invalid: "
            f"{class_name}.{method_name}",
        )

    flow_tree = _tool_tree(root, UNIFIED_FLOW_SOURCE_PATH)
    dispatch = _class_method(
        flow_tree,
        class_name="UnifiedGuideFlow",
        method_name="_dispatch",
    )
    _require(
        dispatch is not None
        and all(
            _call_name(call).rsplit(".", 1)[-1]
            != "notify_processor_entry"
            for call in _executable_call_nodes(
                dispatch,
                known_false_names=_module_type_checking_aliases(flow_tree),
                known_false_attributes=(
                    _module_type_checking_attributes(flow_tree)
                ),
            )
        ),
        "dispatcher processor entry observation is forbidden",
    )


def _validate_runtime_registration_owner(root: Path) -> None:
    writer_module = "tools.guide_gates.attempt_ledger"
    writer_symbol = "register_runtime_bound_attempt"
    calls: list[tuple[str, str, int]] = []
    tool_root = root / "tools/guide_gates"
    for path in sorted(tool_root.rglob("*.py")):
        if path.is_symlink() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        tree = _tool_tree(root, relative)
        direct_aliases: set[str] = set()
        module_aliases: set[str] = set()
        for statement in tree.body:
            if (
                isinstance(statement, ast.ImportFrom)
                and statement.module == writer_module
            ):
                direct_aliases.update(
                    alias.asname or alias.name
                    for alias in statement.names
                    if alias.name == writer_symbol
                )
            elif (
                isinstance(statement, ast.ImportFrom)
                and statement.module == "tools.guide_gates"
            ):
                module_aliases.update(
                    alias.asname or alias.name
                    for alias in statement.names
                    if alias.name == "attempt_ledger"
                )
            elif isinstance(statement, ast.Import):
                module_aliases.update(
                    alias.asname or alias.name
                    for alias in statement.names
                    if alias.name == writer_module
                )

        def is_writer_call(call: ast.Call) -> bool:
            name = _call_name(call)
            return (
                isinstance(call.func, ast.Name)
                and call.func.id in direct_aliases
            ) or name == f"{writer_module}.{writer_symbol}" or any(
                name == f"{alias}.{writer_symbol}"
                for alias in module_aliases
            )

        for function_name, function in _tool_functions(tree).items():
            for call in _executable_call_nodes(
                function,
                known_false_names=_module_type_checking_aliases(tree),
                known_false_attributes=(
                    _module_type_checking_attributes(tree)
                ),
            ):
                if is_writer_call(call):
                    calls.append((relative, function_name, call.lineno))
    _require(
        len(calls) == 1
        and calls[0][0]
        == "tools/guide_gates/run_bound_runtime.py"
        and calls[0][1] == "run_bound_runtime",
        "runtime registration owner is not unique",
    )


def _validate_task12_execution_tools(
    *,
    root: Path,
    manifest: Mapping[str, object],
) -> dict[str, str]:
    source_paths = manifest.get("source_paths")
    tool_paths = manifest.get("tool_paths")
    test_paths = manifest.get("test_paths")
    fixture_paths = manifest.get("fixture_paths")
    _require(
        isinstance(source_paths, list)
        and set(TASK12_RUNTIME_DATA_PATHS) <= set(source_paths),
        "Task 12 backend runtime data is absent from the protected manifest",
    )
    _require(
        isinstance(tool_paths, list)
        and set(TASK12_TOOL_PATHS) <= set(tool_paths),
        "Task 12 execution tools are absent from the protected manifest",
    )
    _require(
        isinstance(test_paths, list)
        and set(TASK12_TEST_PATHS) <= set(test_paths),
        "Task 12 execution tests are absent from the protected manifest",
    )
    _require(
        isinstance(fixture_paths, list)
        and set(TASK12_FIXTURE_PATHS) <= set(fixture_paths),
        "Task 12 v5 fixture is absent from the protected manifest",
    )
    required_paths = (
        *TASK12_TOOL_PATHS,
        *TASK12_TEST_PATHS,
        *TASK12_FIXTURE_PATHS,
        *TASK12_RUNTIME_DATA_PATHS,
    )
    hashes: dict[str, str] = {}
    for relative in required_paths:
        path = root / relative
        _require(
            path.is_file() and not path.is_symlink(),
            f"Task 12 execution file is missing or invalid: {relative}",
        )
        hashes[relative] = _digest_file(path)

    trees = {
        relative: _tool_tree(root, relative)
        for relative in TASK12_TOOL_PATHS
    }
    _validate_runtime_registration_owner(root)
    ledger = trees["tools/guide_gates/attempt_ledger.py"]
    _require_cli_surface(
        ledger,
        required_strings=(
            "authorize",
            "allocate",
            "allocate-child",
            "current",
            "latest",
            "bounded",
            "translation",
            "browser",
            "backend",
            "passed",
            "failed",
        ),
        required_arguments=(
            "--phase",
            "--readiness",
            "--ledger",
            "--authorization-id",
            "--output-root",
            "--parent-context",
            "--require-summary-phase",
            "--require-summary-result",
        ),
        label="attempt ledger",
    )
    _require_tool_calls(
        ledger,
        entry="main",
        required=("authorize_attempt", "allocate_attempt"),
        label="attempt ledger",
    )
    _require_tool_calls(
        ledger,
        entry="authorize_attempt",
        required=(
            "_retry_authorization_from_verified_ledger",
        ),
        label="attempt ledger retry closure",
    )
    _require_tool_calls(
        ledger,
        entry="authorize_attempt",
        required=("_verify_retry_repair_artifacts",),
        label="attempt ledger retry repair validation",
    )
    authorize_attempt = _tool_functions(ledger).get(
        "authorize_attempt"
    )
    authorization_receipt_calls = (
        [
            _call_name(call)
            for call in _executable_call_nodes(
                authorize_attempt,
                known_false_names=_module_type_checking_aliases(
                    ledger
                ),
                known_false_attributes=(
                    _module_type_checking_attributes(ledger)
                ),
            )
        ]
        if authorize_attempt is not None
        else []
    )
    _require(
        authorization_receipt_calls.count(
            "_verify_authorization_receipts"
        )
        == 1
        and authorization_receipt_calls.count(
            "_verify_persisted_attempt_contexts"
        )
        == 1
        and authorization_receipt_calls.count(
            "_write_authorization_receipt"
        )
        == 2,
        "attempt ledger authorization receipt is invalid",
    )
    _require_tool_calls(
        ledger,
        entry="_write_authorization_receipt",
        required=("_write_bound_immutable_json",),
        label="attempt ledger authorization receipt",
    )
    _require_tool_calls(
        ledger,
        entry="_write_checkpoint_authority",
        required=("_write_bound_immutable_json",),
        label="attempt ledger checkpoint authority",
    )
    _require_tool_calls(
        ledger,
        entry="allocate_attempt",
        required=(
            "_verify_persisted_attempt_contexts",
            "_verify_authorization_receipts",
            "_write_attempt_context_witness",
        ),
        label="attempt ledger authorization receipt",
    )
    allocate_attempt = _tool_functions(ledger).get(
        "allocate_attempt"
    )
    allocation_calls = (
        [
            call
            for call in _executable_call_nodes(
                allocate_attempt,
                known_false_names=_module_type_checking_aliases(
                    ledger
                ),
                known_false_attributes=(
                    _module_type_checking_attributes(ledger)
                ),
            )
        ]
        if allocate_attempt is not None
        else []
    )
    allocation_commit_lines = [
        call.lineno
        for call in allocation_calls
        if _call_name(call) == "_atomic_write_ledger"
    ]
    allocation_witness_lines = [
        call.lineno
        for call in allocation_calls
        if _call_name(call) == "_write_attempt_context_witness"
    ]
    allocation_receipt_guards = [
        node
        for node in ast.walk(allocate_attempt)
        if (
            isinstance(node, ast.If)
            and ast.unparse(node.test)
            == "authorization_id not in verified_receipts"
            and any(
                isinstance(child, ast.Raise)
                for statement in node.body
                for child in ast.walk(statement)
            )
        )
    ] if allocate_attempt is not None else []
    _require(
        len(allocation_commit_lines) == 1
        and len(allocation_witness_lines) == 3
        and max(allocation_witness_lines)
        > allocation_commit_lines[0],
        "attempt ledger authorization receipt is invalid",
    )
    _require(
        len(allocation_receipt_guards) == 1
        and sum(
            _call_name(call) == "_verify_authorization_receipts"
            for call in allocation_calls
        )
        == 1
        and sum(
            _call_name(call) == "_verify_persisted_attempt_contexts"
            for call in allocation_calls
        )
        == 2,
        "attempt ledger authorization receipt is invalid",
    )
    _require_tool_calls(
        ledger,
        entry="_verify_persisted_attempt_contexts",
        required=(
            "_attempt_context_witness_name",
            "_read_attempt_context_once",
        ),
        label="attempt ledger authorization receipt",
    )
    ledger_functions = _tool_functions(ledger)
    context_verifier = ledger_functions.get(
        "_verify_persisted_attempt_contexts"
    )
    _require(
        context_verifier is not None
        and any(
            isinstance(node, ast.Name)
            and node.id == "_REPO_ROOT"
            for node in ast.walk(context_verifier)
        )
        and any(
            isinstance(node, ast.If)
            and ast.unparse(node.test)
            == "witness_attempt_id is not None"
            and any(
                isinstance(child, ast.Raise)
                for child in node.body
            )
            for node in ast.walk(context_verifier)
        ),
        "attempt ledger authorization receipt is invalid",
    )
    immutable_writer = ledger_functions.get(
        "_write_bound_immutable_json"
    )
    immutable_writer_calls = (
        {
            _call_name(call)
            for call in _executable_call_nodes(
                immutable_writer,
                known_false_names=_module_type_checking_aliases(
                    ledger
                ),
                known_false_attributes=(
                    _module_type_checking_attributes(ledger)
                ),
            )
        }
        if immutable_writer is not None
        else set()
    )
    _require(
        "os.link" in immutable_writer_calls
        and "os.replace" not in immutable_writer_calls
        and any(
            isinstance(node, ast.Name)
            and node.id == "_NO_FOLLOW"
            for node in ast.walk(immutable_writer)
        ),
        "attempt ledger immutable sidecar commit is invalid",
    )
    receipt_payload = ledger_functions.get(
        "_authorization_receipt_payload"
    )
    receipt_digest_arguments = (
        [
            ast.unparse(call.args[0])
            for call in _executable_call_nodes(
                receipt_payload,
                known_false_names=_module_type_checking_aliases(
                    ledger
                ),
                known_false_attributes=(
                    _module_type_checking_attributes(ledger)
                ),
            )
            if _call_name(call) == "_canonical_bytes"
            and call.args
        ]
        if receipt_payload is not None
        else []
    )
    _require(
        receipt_digest_arguments == ["immutable_authorization"]
        and any(
            isinstance(node, ast.Name)
            and node.id == "_AUTHORIZATION_IMMUTABLE_KEYS"
            for node in ast.walk(receipt_payload)
        ),
        "attempt ledger authorization receipt is invalid",
    )
    authorization_key_assignments = [
        node
        for node in ledger.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "_AUTHORIZATION_IMMUTABLE_KEYS"
                for target in node.targets
            )
        )
    ]
    authorization_key_values = (
        {
            str(element.value)
            for element in authorization_key_assignments[0].value.args[0].elts
            if (
                isinstance(element, ast.Constant)
                and isinstance(element.value, str)
            )
        }
        if (
            len(authorization_key_assignments) == 1
            and isinstance(
                authorization_key_assignments[0].value,
                ast.Call,
            )
            and authorization_key_assignments[0].value.args
            and isinstance(
                authorization_key_assignments[0].value.args[0],
                ast.Set,
            )
        )
        else set()
    )
    _require(
        authorization_key_values
        == {
            "authorization_id",
            "phase",
            "plan_revision",
            "repair_epoch",
            "first_failure_owner",
            "readiness_path",
            "readiness_sha256",
            "expected_manifest_sha256",
            "independent_audit_path",
            "independent_audit_sha256",
            "repair_evidence",
            "created_at",
        },
        "attempt ledger authorization receipt is invalid",
    )
    receipt_verifier = ledger_functions.get(
        "_verify_authorization_receipts"
    )
    _require(
        receipt_verifier is not None
        and any(
            isinstance(node, ast.If)
            and ast.unparse(node.test)
            == (
                "authorization_ids - present_authorization_ids - "
                "allowed_missing_authorization_ids"
            )
            and any(
                isinstance(child, ast.Raise)
                for statement in node.body
                for child in ast.walk(statement)
            )
            for node in ast.walk(receipt_verifier)
        ),
        "attempt ledger authorization receipt is invalid",
    )
    partial_guards = (
        {
            ast.unparse(node.test)
            for node in ast.walk(immutable_writer)
            if (
                isinstance(node, ast.If)
                and any(
                    isinstance(child, ast.Raise)
                    for statement in node.body
                    for child in ast.walk(statement)
                )
            )
        }
        if immutable_writer is not None
        else set()
    )
    _require(
        {
            (
                "len(current) >= len(data) or "
                "not data.startswith(current)"
            ),
            (
                "len(pending) >= len(data) or "
                "not data.startswith(pending)"
            ),
        }
        <= partial_guards,
        "attempt ledger immutable sidecar commit is invalid",
    )
    _require_tool_calls(
        ledger,
        entry="_retry_authorization_from_verified_ledger",
        required=("_latest_failure", "_failure_counts"),
        label="attempt ledger retry derivation",
    )
    allocate_main = _tool_functions(ledger)["main"]
    allocate_calls = [
        node
        for node in _executable_call_nodes(
            allocate_main,
            known_false_names=_module_type_checking_aliases(ledger),
            known_false_attributes=(
                _module_type_checking_attributes(ledger)
            ),
        )
        if _call_name(node).rsplit(".", 1)[-1] == "allocate_attempt"
    ]
    allocate_keywords = (
        {
            keyword.arg: ast.unparse(keyword.value)
            for keyword in allocate_calls[0].keywords
        }
        if len(allocate_calls) == 1
        else {}
    )
    _require(
        len(allocate_calls) == 1
        and allocate_keywords.get("require_summary_phase")
        == (
            "args.require_summary_phase "
            "if args.command == 'allocate-child' else None"
        )
        and allocate_keywords.get("require_summary_result")
        == (
            "args.require_summary_result "
            "if args.command == 'allocate-child' else None"
        ),
        "attempt ledger parent summary requirements are not forwarded",
    )
    _require_tool_calls(
        ledger,
        entry="_required_parent_summary",
        required=("_validate_passed_backend_evidence", "_checksum_bundle"),
        label="attempt ledger backend evidence",
    )
    _require_tool_calls(
        ledger,
        entry="_validate_passed_backend_evidence",
        required=(
            "_backend_sse_events",
            "_backend_sse_payloads_match",
        ),
        label="attempt ledger backend raw SSE evidence",
    )
    _require_tool_calls(
        ledger,
        entry="complete_attempt",
        required=(
            "_validate_passed_bounded_browser_evidence",
            "_validate_passed_translation_evidence",
            "_validate_passed_release_browser_evidence",
            "_terminal_evidence_manifest",
            "validate_runtime_bound_attempt_attestation",
        ),
        label="attempt ledger terminal evidence",
    )
    _require_tool_calls(
        ledger,
        entry="consume_runtime_bound_attempt",
        required=(
            "_verify_live_bound_runtime_identity",
            "_consume_attempt_context_locked",
        ),
        label="attempt ledger live runtime attestation",
    )
    _require_tool_calls(
        ledger,
        entry="_consume_attempt_context_locked",
        required=(
            "_request_live_runtime_proof",
            "verify_runtime_proof",
            "_append_revision",
        ),
        label="attempt ledger signed runtime proof",
    )
    _require_local_imported_call(
        ledger,
        entry="_validate_passed_bounded_browser_evidence",
        imported_module=(
            "tools.guide_gates.run_mainline_contract_browser_audit"
        ),
        imported_symbol="validate_completed_bounded_browser_evidence",
        label="attempt ledger bounded browser evidence",
    )
    lock_function = _tool_functions(ledger).get("_lock_path")
    _require(
        lock_function is not None
        and any(
            isinstance(node, ast.Name)
            and node.id == "_LOCK_DIRECTORY"
            for node in ast.walk(lock_function)
        ),
        "attempt ledger lock is not isolated from the evidence directory",
    )
    _require_tool_calls(
        ledger,
        entry="_ledger_lock",
        required=("_bound_ledger_path", "_verify_bound_ledger_parent"),
        label="attempt ledger path binding",
    )
    _require_tool_calls(
        ledger,
        entry="_ledger_lock",
        required=("_bound_external_ledger_lock",),
        label="attempt ledger lock inode binding",
    )
    _require_tool_calls(
        ledger,
        entry="_bound_external_ledger_lock",
        required=(
            "_open_lock_root_descriptor",
            "_open_lock_directory_descriptor",
            "_lock_path",
            "_verify_bound_lock_file",
        ),
        label="attempt ledger lock inode binding",
    )
    _require_tool_calls(
        ledger,
        entry="_open_lock_root_descriptor",
        required=("_lock_anchor_path",),
        label="attempt ledger lock inode binding",
    )
    external_lock = _tool_functions(ledger).get(
        "_bound_external_ledger_lock"
    )
    lock_open_calls = (
        [
            call
            for call in ast.walk(external_lock)
            if isinstance(call, ast.Call)
            and _call_name(call) == "os.open"
        ]
        if external_lock is not None
        else []
    )
    lock_open_keywords = (
        {
            keyword.arg: ast.unparse(keyword.value)
            for keyword in lock_open_calls[0].keywords
            if keyword.arg is not None
        }
        if len(lock_open_calls) == 1
        else {}
    )
    _require(
        len(lock_open_calls) == 1
        and any(
            isinstance(node, ast.Name)
            and node.id == "_NO_FOLLOW"
            for node in ast.walk(lock_open_calls[0])
        )
        and lock_open_keywords.get("dir_fd")
        == "directory_descriptor",
        "attempt ledger lock inode binding is invalid",
    )
    _require_tool_calls(
        ledger,
        entry="checkpoint_ledger",
        required=(
            "_read_checkpoint_authority",
            "_write_checkpoint_authority",
            "_validate_checkpoint_authority",
            "_verify_published_readiness_anchors",
        ),
        label="attempt ledger checkpoint authority",
    )
    _require_tool_calls(
        ledger,
        entry="_read_regular_file_once",
        required=("_bound_ledger_path", "_verify_bound_ledger_parent"),
        label="attempt ledger path binding",
    )
    atomic_write = _tool_functions(ledger).get("_atomic_write_ledger")
    replace_calls = (
        [
            call
            for call in _executable_call_nodes(
                atomic_write,
                known_false_names=_module_type_checking_aliases(ledger),
                known_false_attributes=(
                    _module_type_checking_attributes(ledger)
                ),
            )
            if _call_name(call) == "os.replace"
        ]
        if atomic_write is not None
        else []
    )
    replace_keywords = (
        {
            keyword.arg: ast.unparse(keyword.value)
            for keyword in replace_calls[0].keywords
            if keyword.arg is not None
        }
        if len(replace_calls) == 1
        else {}
    )
    _require(
        replace_keywords.get("src_dir_fd")
        == "binding.parent_descriptor"
        and replace_keywords.get("dst_dir_fd")
        == "binding.parent_descriptor",
        "attempt ledger path binding does not own atomic replace",
    )

    readiness = trees[
        "tools/guide_gates/build_task11_readiness.py"
    ]
    _validate_readiness_completion_source(readiness)
    cleanup_function = _tool_functions(readiness).get(
        "_unlink_validated_runtime_private_key"
    )
    cleanup_empty_content_branches = (
        [
            node
            for node in ast.walk(cleanup_function)
            if (
                isinstance(node, ast.If)
                and ast.unparse(node.test)
                == "not content"
            )
        ]
        if cleanup_function is not None
        else []
    )
    _require(
        len(cleanup_empty_content_branches) == 1
        and any(
            isinstance(child, ast.Raise)
            for statement in cleanup_empty_content_branches[0].body
            for child in ast.walk(statement)
        )
        and not any(
            isinstance(child, ast.Return)
            for statement in cleanup_empty_content_branches[0].body
            for child in ast.walk(statement)
        ),
        "runtime key cleanup resume is invalid",
    )
    _require_tool_calls(
        readiness,
        entry="_unlink_validated_runtime_private_key",
        required=(
            "_runtime_private_key_destruction_receipt",
            "_write_runtime_private_key_destruction_receipt",
        ),
        label="runtime key cleanup resume",
    )
    destruction_receipt = _tool_functions(readiness).get(
        "_runtime_private_key_destruction_receipt"
    )
    destruction_receipt_fields = (
        {
            str(key.value): ast.unparse(value)
            for node in ast.walk(destruction_receipt)
            if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values, strict=True)
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
            )
        }
        if destruction_receipt is not None
        else {}
    )
    _require(
        destruction_receipt_fields.get("key_device")
        == "key_metadata.st_dev"
        and destruction_receipt_fields.get("key_inode")
        == "key_metadata.st_ino"
        and destruction_receipt_fields.get("key_sha256")
        == "sha256(key_content).hexdigest()",
        "runtime key cleanup resume is invalid",
    )
    _require_tool_calls(
        readiness,
        entry="_validate_runtime_private_key_destruction_receipt",
        required=("_verify_runtime_signature",),
        label="runtime key cleanup resume",
    )
    cleanup_calls = (
        list(
            _executable_call_nodes(
                cleanup_function,
                known_false_names=_module_type_checking_aliases(
                    readiness
                ),
                known_false_attributes=(
                    _module_type_checking_attributes(readiness)
                ),
            )
        )
        if cleanup_function is not None
        else []
    )
    cleanup_receipt_lines = [
        call.lineno
        for call in cleanup_calls
        if _call_name(call)
        == "_write_runtime_private_key_destruction_receipt"
    ]
    tombstone_unlink_lines = [
        call.lineno
        for call in cleanup_calls
        if (
            _call_name(call) == "os.unlink"
            and call.args
            and ast.unparse(call.args[0]) == "tombstone_name"
        )
    ]
    truncate_lines = [
        call.lineno
        for call in cleanup_calls
        if _call_name(call) == "os.ftruncate"
    ]
    _require(
        len(cleanup_receipt_lines) == 1
        and len(tombstone_unlink_lines) == 1
        and len(truncate_lines) == 1
        and any(
            _call_name(call) == "os.link"
            for call in cleanup_calls
        )
        and cleanup_receipt_lines[0] < tombstone_unlink_lines[0]
        < truncate_lines[0],
        "runtime key cleanup resume is invalid",
    )
    _require_tool_calls(
        readiness,
        entry="_require_runtime_private_keys_destroyed",
        required=(
            "_verify_runtime_private_key_destruction_receipt_file",
        ),
        label="runtime key cleanup receipt",
    )
    seal_readiness = _tool_functions(readiness).get(
        "seal_candidate_readiness"
    )
    seal_key_checks = (
        [
            call
            for call in _executable_call_nodes(
                seal_readiness,
                known_false_names=_module_type_checking_aliases(
                    readiness
                ),
                known_false_attributes=(
                    _module_type_checking_attributes(readiness)
                ),
            )
            if _call_name(call)
            == "_require_runtime_private_keys_destroyed"
        ]
        if seal_readiness is not None
        else []
    )
    _require(
        len(seal_key_checks) == 2
        and all(
            {
                keyword.arg
                for keyword in call.keywords
                if keyword.arg is not None
            }
            == {
                "repo_root",
                "manifest_sha256",
                "runtime_public_keys",
                "selected_slot",
            }
            for call in seal_key_checks
        ),
        "runtime key cleanup receipt is invalid",
    )
    _require_tool_calls(
        readiness,
        entry="_require_readiness_publication_authority",
        required=(
            "_require_readiness_parent_binding",
            "canonical_payload_sha256",
            "_require_runtime_private_keys_destroyed",
        ),
        label="candidate readiness publication",
    )
    _require_tool_calls(
        readiness,
        entry="_write_readiness_exclusive",
        required=("_require_readiness_publication_authority",),
        label="candidate readiness publication",
    )
    readiness_writer = _tool_functions(readiness).get(
        "_write_readiness_exclusive"
    )
    readiness_writer_calls = (
        list(
            _executable_call_nodes(
                readiness_writer,
                known_false_names=_module_type_checking_aliases(
                    readiness
                ),
                known_false_attributes=(
                    _module_type_checking_attributes(readiness)
                ),
            )
        )
        if readiness_writer is not None
        else []
    )
    publication_authority_lines = [
        call.lineno
        for call in readiness_writer_calls
        if _call_name(call)
        == "_require_readiness_publication_authority"
    ]
    publication_link_lines = [
        call.lineno
        for call in readiness_writer_calls
        if (
            _call_name(call) == "os.link"
            and len(call.args) >= 2
            and ast.unparse(call.args[0]) == "pending_name"
            and ast.unparse(call.args[1]) == "path.name"
        )
    ]
    publication_ordered = False
    if readiness_writer is not None and len(publication_link_lines) == 1:
        for node in ast.walk(readiness_writer):
            for field in ("body", "orelse", "finalbody"):
                statements = getattr(node, field, None)
                if not isinstance(statements, list):
                    continue
                for previous, current in zip(
                    statements,
                    statements[1:],
                    strict=False,
                ):
                    if (
                        isinstance(previous, ast.Expr)
                        and isinstance(previous.value, ast.Call)
                        and _call_name(previous.value)
                        == "_require_readiness_publication_authority"
                        and isinstance(current, ast.Expr)
                        and isinstance(current.value, ast.Call)
                        and _call_name(current.value) == "os.link"
                        and current.value.lineno
                        == publication_link_lines[0]
                    ):
                        publication_ordered = True
    post_link_rollback = False
    if readiness_writer is not None and len(publication_link_lines) == 1:
        link_line = publication_link_lines[0]
        for node in ast.walk(readiness_writer):
            if not isinstance(node, ast.Try):
                continue
            body_calls = [
                child
                for statement in node.body
                for child in ast.walk(statement)
                if isinstance(child, ast.Call)
            ]
            if not any(
                _call_name(call)
                == "_require_readiness_publication_authority"
                and call.lineno > link_line
                for call in body_calls
            ):
                continue
            for handler in node.handlers:
                handler_calls = [
                    child
                    for statement in handler.body
                    for child in ast.walk(statement)
                    if isinstance(child, ast.Call)
                ]
                if (
                    _call_name(handler.type)
                    == "Task11ReadinessError"
                    and any(
                        _call_name(call) == "os.unlink"
                        and call.args
                        and ast.unparse(call.args[0]) == "path.name"
                        for call in handler_calls
                    )
                    and any(
                        _call_name(call) == "os.fsync"
                        and call.args
                        and ast.unparse(call.args[0])
                        == "parent_descriptor"
                        for call in handler_calls
                    )
                ):
                    post_link_rollback = True
    recovery_guards = (
        {
            ast.unparse(node.test)
            for node in ast.walk(readiness_writer)
            if (
                isinstance(node, ast.If)
                and any(
                    isinstance(child, ast.Raise)
                    for statement in node.body
                    for child in ast.walk(statement)
                )
            )
        }
        if readiness_writer is not None
        else set()
    )
    _require(
        len(publication_authority_lines) == 3
        and len(publication_link_lines) == 1
        and publication_ordered
        and sum(
            line < publication_link_lines[0]
            for line in publication_authority_lines
        )
        == 2
        and sum(
            line > publication_link_lines[0]
            for line in publication_authority_lines
        )
        == 1
        and post_link_rollback
        and not any(
            _call_name(call) == "os.replace"
            for call in readiness_writer_calls
        )
        and any(
            "len(current) > len(data)" in guard
            and "not data.startswith(current)" in guard
            for guard in recovery_guards
        ),
        "candidate readiness publication is invalid",
    )

    zero_runtime = trees[
        "tools/guide_gates/run_zero_api_runtime.py"
    ]
    consume_key = _tool_functions(zero_runtime).get(
        "_consume_runtime_private_key_file"
    )
    consume_calls = (
        list(
            _executable_call_nodes(
                consume_key,
                known_false_names=_module_type_checking_aliases(
                    zero_runtime
                ),
                known_false_attributes=(
                    _module_type_checking_attributes(zero_runtime)
                ),
            )
        )
        if consume_key is not None
        else []
    )
    consume_unlink_lines = [
        call.lineno
        for call in consume_calls
        if (
            _call_name(call) == "os.unlink"
            and call.args
            and ast.unparse(call.args[0]) == "canonical_path.name"
            and {
                keyword.arg: ast.unparse(keyword.value)
                for keyword in call.keywords
                if keyword.arg is not None
            }.get("dir_fd")
            == "parent_descriptor"
        )
    ]
    consume_parent_fsync_lines = [
        call.lineno
        for call in consume_calls
        if (
            _call_name(call) == "os.fsync"
            and len(call.args) == 1
            and ast.unparse(call.args[0]) == "parent_descriptor"
        )
    ]
    consume_truncate_lines = [
        call.lineno
        for call in consume_calls
        if (
            _call_name(call) == "os.ftruncate"
            and len(call.args) == 2
            and ast.unparse(call.args[0]) == "descriptor"
            and ast.unparse(call.args[1]) == "0"
        )
    ]
    _require(
        len(consume_unlink_lines) == 1
        and len(consume_parent_fsync_lines) == 1
        and len(consume_truncate_lines) == 1
        and consume_unlink_lines[0]
        < consume_parent_fsync_lines[0]
        < consume_truncate_lines[0],
        "runtime key consumption order is invalid",
    )
    _require_cli_surface(
        readiness,
        required_strings=(
            "seal-commit",
            "verify-release-readiness",
            "--manifest",
            "--candidate-readiness",
            "--release-readiness",
            "--task11-commit",
            "--readiness",
            "--require-head",
        ),
        required_arguments=(
            "--manifest",
            "--candidate-readiness",
            "--release-readiness",
            "--task11-commit",
            "--readiness",
            "--require-head",
        ),
        label="release readiness",
    )
    _require_tool_calls(
        readiness,
        entry="main",
        required=("seal_task11_commit", "verify_release_readiness"),
        label="release readiness",
    )
    _require_tool_calls(
        readiness,
        entry="_require_manifest_ledger_checkpoint",
        required=("verify_ledger_checkpoint_authority",),
        label="checkpoint authority",
    )
    _require_tool_calls(
        readiness,
        entry="build_test_path_audit",
        required=("_production_path_test_executes_runner",),
        label="test path production claim",
    )
    _require_tool_calls(
        readiness,
        entry="build_change_manifest",
        required=(
            "_readiness_fixture_artifact_paths",
            "_validated_bounded_attempt_artifacts",
        ),
        label="bounded change manifest evidence",
    )
    _require_tool_calls(
        readiness,
        entry="_validated_bounded_attempt_artifacts",
        required=(
            "_validate_completed_bounded_evidence",
            "validate_runtime_bound_attempt_attestation",
        ),
        label="bounded attempt artifact validation",
    )
    _require_tool_calls(
        readiness,
        entry="finalize_change_manifest",
        required=(
            "verify_task11_readiness",
            "_readiness_fixture_artifact_paths",
            "_validated_bounded_attempt_artifacts",
        ),
        label="change manifest finalization",
    )
    _require_tool_calls(
        readiness,
        entry="seal_task11_commit",
        required=(
            "verify_task11_readiness",
            "_readiness_fixture_artifact_paths",
            "_validated_bounded_attempt_artifacts",
        ),
        label="commit seal readiness",
    )
    _require_tool_calls(
        readiness,
        entry="verify_release_readiness",
        required=(
            "verify_task11_readiness",
            "_readiness_fixture_artifact_paths",
        ),
        label="release readiness fixture artifacts",
    )
    _require_module_import(
        readiness,
        imported_module="tools.guide_gates.attempt_ledger",
        imported_symbol="validate_runtime_bound_attempt_attestation",
        label="bounded change manifest runtime attestation",
    )

    translation = trees[
        "tools/guide_gates/run_final_real_translation.py"
    ]
    _require(
        any(
            value.endswith("real_translation_12x4_v5.jsonl")
            for value in _module_strings(translation)
        )
        and {"fixture_path", "fixture_sha256"}
        <= _class_field_names(translation, "FinalTranslationReport"),
        "final translation CLI does not default to the v5 fixture",
    )
    _require(
        "image_product_ids"
        in _class_field_names(translation, "FinalTranslationTurn"),
        "final translation fixture does not bind image inputs",
    )
    _require_cli_surface(
        translation,
        required_strings=(
            "--cases",
            "--attempt-context",
            "--phase",
            "--state-dir",
            "translation",
        ),
        required_arguments=(
            "--attempt-context",
            "--phase",
            "--state-dir",
        ),
        label="final translation",
    )
    _require_tool_calls(
        translation,
        entry="main",
        required=("run_authorized_final_translation",),
        label="final translation",
    )
    _require_tool_calls(
        translation,
        entry="run_authorized_final_translation",
        required=(
            "verify_task11_readiness",
            "consume_attempt_context",
            "DeepSeekTurnMeaningAdapter",
            "_focused_summary_sha256",
            "validate_final_translation_fixture",
            "complete_attempt",
        ),
        label="final translation",
    )
    _require_tool_calls(
        translation,
        entry="run_authorized_final_translation",
        required=("build_provider_usage_limiter",),
        label="final translation provider quota",
    )
    _require_call_order(
        translation,
        function_name="run_authorized_final_translation",
        before="build_provider_usage_limiter",
        after="consume_attempt_context",
        label="final translation provider quota",
    )
    translation_run = _tool_functions(translation).get(
        "run_authorized_final_translation"
    )
    adapter_calls = (
        [
            call
            for call in _executable_call_nodes(
                translation_run,
                known_false_names=_module_type_checking_aliases(translation),
                known_false_attributes=(
                    _module_type_checking_attributes(translation)
                ),
            )
            if _call_name(call).rsplit(".", 1)[-1]
            == "DeepSeekTurnMeaningAdapter"
        ]
        if translation_run is not None
        else []
    )
    adapter_keywords = (
        {
            keyword.arg: ast.unparse(keyword.value)
            for keyword in adapter_calls[0].keywords
            if keyword.arg is not None
        }
        if len(adapter_calls) == 1
        else {}
    )
    _require(
        adapter_keywords.get("usage_limiter") == "usage_limiter",
        "final translation provider quota is not shared",
    )
    _require_call_order(
        translation,
        function_name="run_authorized_final_translation",
        before="verify_task11_readiness",
        after="consume_attempt_context",
        label="final translation",
    )

    backend = trees[
        "tools/guide_gates/replay_final_real_backend.py"
    ]
    _require(
        "real_translation_12x4_v5.jsonl" in _module_strings(backend)
        and {
            "fixture_path",
            "fixture_sha256",
            "context_mismatch_count",
            "context_replay_mode",
            "stateful_transition_count",
            "translation_results_sha256",
            "translation_summary_sha256",
            "translation_checksums_sha256",
        }
        <= _class_field_names(backend, "BackendReplayReport"),
        "backend replay does not bind the v5 translation capture",
    )
    _require(
        {
            "image_product_ids",
            "image_asset_sha256s",
            "raw_sse_path",
            "raw_sse_sha256",
            "sealed_context_sha256",
            "observed_context_sha256",
            "context_mismatch_count",
        }
        <= _class_field_names(backend, "BackendReplayTurnTrace"),
        "backend replay does not prove sealed context, image, or raw SSE identity",
    )
    _require_cli_surface(
        backend,
        required_strings=(
            "--attempt-context",
            "--phase",
            "backend",
        ),
        required_arguments=("--attempt-context", "--phase"),
        label="backend replay",
    )
    _require_tool_calls(
        backend,
        entry="main",
        required=(
            "replay_final_real_backend",
            "verify_task11_readiness",
            "validate_final_translation_fixture",
        ),
        label="backend replay",
    )
    _require_tool_calls(
        backend,
        entry="_run_http_replay",
        required=(
            "_materialize_replay_snapshot",
            "_seed_replay_snapshot",
            "_upload_replay_images",
        ),
        label="backend sealed context",
    )
    replay_function = _tool_functions(backend)["_run_http_replay"]
    backend_false_names = _module_type_checking_aliases(backend)
    backend_false_attributes = _module_type_checking_attributes(
        backend
    )
    provider_bindings = [
        node
        for node in _executable_call_nodes(
            replay_function,
            known_false_names=backend_false_names,
            known_false_attributes=backend_false_attributes,
        )
        if _call_name(node) == "provider.bind"
    ]
    expected_context_arguments = [
        ast.unparse(keyword.value)
        for call in provider_bindings
        for keyword in call.keywords
        if keyword.arg == "expected_context"
    ]
    _require(
        len(provider_bindings) == 1
        and expected_context_arguments == ["turn.case.context"],
        "backend replay sealed context binding is invalid",
    )
    image_uploads = [
        node
        for node in _executable_call_nodes(
            replay_function,
            known_false_names=backend_false_names,
            known_false_attributes=backend_false_attributes,
        )
        if _call_name(node) == "_upload_replay_images"
    ]
    image_product_arguments = [
        ast.unparse(keyword.value)
        for call in image_uploads
        for keyword in call.keywords
        if keyword.arg == "image_product_ids"
    ]
    _require(
        len(image_uploads) == 1
        and image_product_arguments == ["turn.image_product_ids"],
        "backend replay case-bound image evidence is invalid",
    )
    _require_tool_calls(
        backend,
        entry="replay_final_real_backend",
        required=("_write_report",),
        label="backend replay raw SSE evidence",
    )

    runtime = trees["tools/guide_gates/run_bound_runtime.py"]
    _require_cli_surface(
        runtime,
        required_strings=(
            "--attempt-context",
            "--host",
            "--port",
            "--state-dir",
        ),
        required_arguments=(
            "--attempt-context",
            "--host",
            "--port",
            "--state-dir",
        ),
        label="bound runtime",
    )
    _require_tool_calls(
        runtime,
        entry="main",
        required=(
            "run_bound_runtime",
            "verify_task11_readiness",
            "_bound_listener",
            "generate_runtime_keypair",
            "register_runtime_bound_attempt",
        ),
        label="bound runtime",
    )
    run_bound_calls = {
        _call_name(node).rsplit(".", 1)[-1]
        for node in ast.walk(_tool_functions(runtime)["run_bound_runtime"])
        if isinstance(node, ast.Call)
    }
    _require(
        {
            "_BoundRuntimeProofApplication",
            "_ProofGatedApplication",
            "validate_runtime_request_authority",
            "runtime_request_lifecycle_lease",
        }
        <= run_bound_calls,
        "bound runtime signed request authority is missing",
    )
    _require(
        "runtime_request_authority_lease" not in run_bound_calls
        and "_bound_attempt_is_consumed"
        not in _tool_functions(runtime),
        "bound runtime has a parallel request authority path",
    )
    runtime_auth = trees["tools/guide_gates/runtime_auth.py"]
    _require_module_import(
        runtime_auth,
        imported_module=(
            "cryptography.hazmat.primitives.asymmetric.ed25519"
        ),
        imported_symbol="Ed25519PrivateKey",
        label="runtime private signing key",
    )
    _require_module_import(
        runtime_auth,
        imported_module=(
            "cryptography.hazmat.primitives.asymmetric.ed25519"
        ),
        imported_symbol="Ed25519PublicKey",
        label="runtime public verification key",
    )
    runtime_auth_functions = _tool_functions(runtime_auth)
    _require(
        {
            "generate_runtime_keypair",
            "sign_runtime_proof",
            "verify_runtime_proof",
        }
        <= set(runtime_auth_functions),
        "runtime asymmetric proof functions are missing",
    )

    browser = trees[
        "tools/guide_gates/run_mainline_contract_browser_audit.py"
    ]
    _require_cli_surface(
        browser,
        required_strings=(
            "--base-url",
            "--trajectory-set",
            "release",
            "--viewport",
            "all",
            "--attempt-context",
        ),
        required_arguments=(
            "--base-url",
            "--trajectory-set",
            "--viewport",
        ),
        label="release browser",
    )
    _require_tool_calls(
        browser,
        entry="main",
        required=("run_authorized_release_browser_audit",),
        label="release browser",
    )
    _require_tool_calls(
        browser,
        entry="run_authorized_release_browser_audit",
        required=(
            "verify_task11_readiness",
            "consume_runtime_bound_attempt",
        ),
        label="release browser",
    )
    _require_call_order(
        browser,
        function_name="run_authorized_release_browser_audit",
        before="verify_task11_readiness",
        after="consume_runtime_bound_attempt",
        label="release browser",
    )
    _require_tool_calls(
        browser,
        entry="run_authorized_bounded_browser_audit",
        required=(
            "verify_task11_readiness",
            "consume_runtime_bound_attempt",
        ),
        label="bounded browser",
    )
    _require_module_import(
        browser,
        imported_module="tools.guide_gates.attempt_ledger",
        imported_symbol="consume_runtime_bound_attempt",
        label="release browser live runtime attestation",
    )
    _require_tool_calls(
        browser,
        entry="run_release_browser_audit",
        required=("derive_release_turn_counters",),
        label="release browser measured counters",
    )
    _require_tool_calls(
        browser,
        entry="_wait_for_live_terminal",
        required=("_capture_count",),
        label="release browser capture count",
    )
    _require_tool_calls(
        browser,
        entry="validate_completed_bounded_browser_evidence",
        required=(
            "validate_audit_bundle",
            "validate_bounded_contract",
            "_artifact_sha256_by_path",
        ),
        label="bounded browser artifact validation",
    )
    _require_tool_calls(
        browser,
        entry="_product_payloads_match_canonical",
        required=(
            "_public_product_matches_canonical",
            "project_frontend_product",
        ),
        label="frontend product projection",
    )
    _require_module_import(
        browser,
        imported_module=(
            "app.guide.application.public_event_envelope"
        ),
        imported_symbol="project_frontend_product",
        label="frontend product projection",
    )
    for entry in (
        "derive_release_turn_counters",
        "validate_audit_bundle",
    ):
        _require_tool_calls(
            browser,
            entry=entry,
            required=(
                "_validate_success_stream_lifecycle",
                "_validate_stream_terminal_ownership",
                "_product_payloads_match_canonical",
            ),
            label="release browser stream lifecycle",
        )

    manual = trees[
        "tools/guide_gates/record_manual_screenshot_review.py"
    ]
    _require_cli_surface(
        manual,
        required_strings=("--attempt-context",),
        required_arguments=("--attempt-context",),
        label="manual screenshot review",
    )
    _require_tool_calls(
        manual,
        entry="main",
        required=(
            "record_manual_screenshot_review",
            "verify_task11_readiness",
        ),
        label="manual screenshot review",
    )

    release = trees[
        "tools/guide_gates/run_final_release_gate.py"
    ]
    _require_cli_surface(
        release,
        required_strings=(
            "focused",
            "aggregate",
            "build-evidence-manifest",
            "stage-evidence",
            "verify-evidence-staging",
            "create-seal",
            "verify-seal",
            "--attempt-context",
            "--phase",
            "--manual-screenshot-review-from-context",
        ),
        required_arguments=(
            "--attempt-context",
            "--phase",
            "--manual-screenshot-review-from-context",
        ),
        label="final release gate",
    )
    release_parser = _tool_functions(release)["_parse_args"]
    _require(
        {
            "build-evidence-manifest",
            "create-seal",
            "verify-seal",
        }
        <= _literal_subparser_names(
            release_parser,
            known_false_names=_module_type_checking_aliases(release),
            known_false_attributes=(
                _module_type_checking_attributes(release)
            ),
        ),
        "final release gate is missing create-seal or another "
        "literal release command",
    )
    _require_tool_calls(
        release,
        entry="main",
        required=(
            "run_focused_phase",
            "run_aggregate_phase",
            "build_evidence_manifest",
            "stage_evidence",
            "verify_evidence_staging",
            "create_release_seal",
            "verify_release_seal",
        ),
        label="final release gate",
    )
    for entry in ("run_focused_phase", "run_aggregate_phase"):
        _require_tool_calls(
            release,
            entry=entry,
            required=("verify_task11_readiness",),
            label=f"final release {entry}",
        )
    _require_tool_calls(
        release,
        entry="run_aggregate_phase",
        required=(
            "_validate_aggregate_bindings",
            "_validate_browser_release_evidence",
            "_indexed_checksum_directory",
            "_indexed_browser_artifacts",
            "derive_release_turn_counters",
            "validate_audit_bundle",
        ),
        label="final release aggregate evidence binding",
    )
    _require_tool_calls(
        release,
        entry="verify_release_seal",
        required=(
            "_validated_committed_evidence_manifest",
            "_sealed_evidence_file",
            "_validate_sealed_release_evidence",
        ),
        label="final release seal evidence binding",
    )
    _require_tool_calls(
        release,
        entry="create_release_seal",
        required=("_validate_sealed_release_evidence",),
        label="final release create-seal evidence binding",
    )
    _require_tool_calls(
        release,
        entry="_validate_sealed_release_evidence",
        required=(
            "_validate_aggregate_bindings",
            "_validate_manual_review_rows",
            "aggregate_release_gate",
        ),
        label="final release sealed evidence recomputation",
    )
    for entry in ("build_evidence_manifest", "create_release_seal"):
        _require_tool_calls(
            release,
            entry=entry,
            required=("_verify_post_real_readiness",),
            label=f"final release {entry}",
        )
    return dict(sorted(hashes.items()))


def _scan_production_architecture(root: Path) -> None:
    violations: list[str] = []
    chat_stream_roots: list[str] = []
    for path in sorted((root / "app").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            violations.append(f"{relative}: symlinked production module")
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise Task11IndependentAuditError(
                f"production architecture source is invalid: {relative}"
            ) from exc
        for class_node in (
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ):
            methods = {
                node.name
                for node in class_node.body
                if isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            }
            if (
                class_node.name == "UnifiedGuideFlow"
                and "stream_image" in methods
            ):
                violations.append(
                    f"{relative}:{class_node.lineno}: parallel unified "
                    "flow entrypoint stream_image"
                )
            if "execute" not in methods:
                continue
            forbidden_methods = sorted(
                methods
                & {
                    "resolve_product_bindings",
                    "resolve_product_resolution",
                }
            )
            for method_name in forbidden_methods:
                violations.append(
                    f"{relative}:{class_node.lineno}: processor "
                    f"pre-routing product resolution capability "
                    f"{method_name}"
                )
            initializer = next(
                (
                    node
                    for node in class_node.body
                    if isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name == "__init__"
                ),
                None,
            )
            if initializer is None:
                continue
            arguments = (
                *initializer.args.posonlyargs,
                *initializer.args.args,
                *initializer.args.kwonlyargs,
            )
            for argument in arguments:
                if argument.arg == "product_name_resolver":
                    violations.append(
                        f"{relative}:{argument.lineno}: processor "
                        "pre-routing product resolution dependency "
                        "product_name_resolver"
                    )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "tests" or alias.name.startswith("tests."):
                        violations.append(
                            f"{relative}:{node.lineno}: imports test seam "
                            f"{alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "tests" or module.startswith("tests."):
                    violations.append(
                        f"{relative}:{node.lineno}: imports test seam {module}"
                    )
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ) and node.name in BRIDGE_SYMBOLS:
                violations.append(
                    f"{relative}:{node.lineno}: forbidden capability "
                    f"{node.name}"
                )
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if name in LEGACY_FLAG_NAMES:
                    violations.append(
                        f"{relative}:{node.lineno}: legacy route flag {name}"
                    )
            if isinstance(node, ast.Call):
                call_name = _call_name(node)
                terminal_name = call_name.rsplit(".", 1)[-1]
                if terminal_name == "stream_image":
                    violations.append(
                        f"{relative}:{node.lineno}: parallel unified "
                        "flow call stream_image"
                    )
                if (
                    relative
                    == "app/guide/presentation/presentation_compiler.py"
                    and terminal_name == "decision_for_responsibility"
                ):
                    violations.append(
                        f"{relative}:{node.lineno}: presentation mode "
                        "rederived after routing"
                    )
                if (
                    terminal_name in {"get", "post", "route"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "/api/v1/chat/stream"
                ):
                    chat_stream_roots.append(
                        f"{relative}:{getattr(node, 'lineno', 0)}"
                    )
                if (
                    terminal_name in {"get", "post", "route"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "/api/v1/chat/message"
                ):
                    violations.append(
                        f"{relative}:{node.lineno}: alternate chat endpoint"
                    )
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            calls = sorted(
                (
                    item
                    for item in ast.walk(function)
                    if isinstance(item, ast.Call)
                ),
                key=lambda item: (item.lineno, item.col_offset),
            )
            save_lines = [
                item.lineno
                for item in calls
                if _call_name(item).rsplit(".", 1)[-1] == "save"
            ]
            if not save_lines:
                continue
            first_save = min(save_lines)
            for call in calls:
                terminal = _call_name(call).rsplit(".", 1)[-1].lower()
                if call.lineno > first_save and any(
                    token in terminal
                    for token in (
                        "dump",
                        "encode",
                        "materialize",
                        "project",
                        "serialize",
                    )
                ):
                    violations.append(
                        f"{relative}:{call.lineno}: post-CAS encoder "
                        f"{_call_name(call)}"
                    )
    if len(chat_stream_roots) > 1:
        violations.append(
            "multiple production chat stream roots: "
            + ", ".join(chat_stream_roots)
        )
    if violations:
        raise Task11IndependentAuditError(
            "production bridge detected: " + "; ".join(violations[:8])
        )


def _collect_pytest_nodes(
    root: Path,
    test_files: Sequence[str],
) -> tuple[str, ...]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            *test_files,
        ],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    _require(
        completed.returncode == 0,
        "pytest node inventory collection failed",
    )
    return tuple(
        line.strip()
        for line in completed.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    )


def _discover_test_fixture_dependencies(
    path: Path,
    *,
    repo_root: Path,
) -> tuple[str, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        raise Task11IndependentAuditError(
            f"test fixture dependency source is invalid: {path}"
        ) from exc
    dependencies = {
        match.group(0).rstrip("./")
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        for match in _TEST_FIXTURE_PATTERN.finditer(node.value)
        if (repo_root / match.group(0).rstrip("./")).is_file()
    }
    bindings: dict[str, tuple[str, ...]] = {}

    def parts(node: ast.AST) -> tuple[str, ...]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return (node.value,)
        if isinstance(node, ast.Name):
            return bindings.get(node.id, ())
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return (*parts(node.left), *parts(node.right))
        return ()

    for statement in tree.body:
        target = None
        value = None
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            target = statement.targets[0]
            value = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
        ):
            target = statement.target
            value = statement.value
        if target is None or value is None:
            continue
        resolved = parts(value)
        if resolved:
            bindings[target.id] = resolved

    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        resolved = parts(node)
        if "fixtures" not in resolved:
            continue
        index = resolved.index("fixtures")
        candidate = (
            resolved[index - 1:]
            if index > 0 and resolved[index - 1] == "tests"
            else ("tests", *resolved[index:])
        )
        relative = PurePosixPath(*candidate).as_posix()
        if (
            relative.startswith("tests/fixtures/guide/")
            and (repo_root / relative).is_file()
        ):
            dependencies.add(relative)
    return tuple(sorted(dependencies))


def _test_node_fixture_dependencies(
    path: Path,
    *,
    node_id: str,
    repo_root: Path,
) -> tuple[str, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        raise Task11IndependentAuditError(
            f"test fixture dependency source is invalid: {path}"
        ) from exc
    test_name = node_id.partition("::")[2].split("[", 1)[0]
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    test = functions.get(test_name)
    _require(test is not None, f"test node source is missing: {node_id}")
    reached: list[ast.AST] = []
    pending = [test]
    seen: set[str] = set()
    while pending:
        function = pending.pop()
        if function.name in seen:
            continue
        seen.add(function.name)
        reached.append(function)
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in functions
                and not node.func.id.startswith("test")
            ):
                pending.append(functions[node.func.id])

    assignments: dict[str, ast.AST] = {}
    imports: dict[str, str] = {}
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            assignments[statement.targets[0].id] = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
        ):
            assignments[statement.target.id] = statement.value
        elif isinstance(statement, ast.ImportFrom) and statement.module:
            for alias in statement.names:
                imports[alias.asname or alias.name] = (
                    f"{statement.module}.{alias.name}"
                )

    loaded_names = {
        node.id
        for root in reached
        for node in ast.walk(root)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    referenced_values = tuple(
        assignments[name]
        for name in loaded_names
        if name in assignments
    )

    def fixture_paths(
        nodes: Sequence[ast.AST],
        *,
        bindings: Mapping[str, ast.AST],
    ) -> set[str]:
        dependencies = {
            match.group(0).rstrip("./")
            for root in nodes
            for node in ast.walk(root)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            for match in _TEST_FIXTURE_PATTERN.finditer(node.value)
            if (repo_root / match.group(0).rstrip("./")).is_file()
        }

        def parts(node: ast.AST) -> tuple[str, ...]:
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
            ):
                return (node.value,)
            if isinstance(node, ast.Name):
                bound = bindings.get(node.id)
                return parts(bound) if bound is not None else ()
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                return (*parts(node.left), *parts(node.right))
            return ()

        for root in nodes:
            for node in ast.walk(root):
                if (
                    not isinstance(node, ast.BinOp)
                    or not isinstance(node.op, ast.Div)
                ):
                    continue
                resolved = parts(node)
                if "fixtures" not in resolved:
                    continue
                index = resolved.index("fixtures")
                candidate = (
                    resolved[index - 1:]
                    if index > 0 and resolved[index - 1] == "tests"
                    else ("tests", *resolved[index:])
                )
                relative = PurePosixPath(*candidate).as_posix()
                if (
                    relative.startswith("tests/fixtures/guide/")
                    and (repo_root / relative).is_file()
                ):
                    dependencies.add(relative)
        return dependencies

    dependencies = fixture_paths(
        (*reached, *referenced_values),
        bindings=assignments,
    )
    for name in sorted(loaded_names):
        imported = imports.get(name)
        if imported is None or "." not in imported:
            continue
        module_name, symbol = imported.rsplit(".", 1)
        module_path = repo_root / (
            module_name.replace(".", "/") + ".py"
        )
        if not module_path.is_file() or module_path.is_symlink():
            continue
        try:
            imported_tree = ast.parse(
                module_path.read_text(encoding="utf-8")
            )
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            raise Task11IndependentAuditError(
                f"imported fixture source is invalid: {imported}"
            ) from exc
        imported_assignments: dict[str, ast.AST] = {}
        for statement in imported_tree.body:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                imported_assignments[
                    statement.targets[0].id
                ] = statement.value
            elif (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and statement.value is not None
            ):
                imported_assignments[
                    statement.target.id
                ] = statement.value
        value = imported_assignments.get(symbol)
        if value is not None:
            dependencies.update(
                fixture_paths(
                    (value,),
                    bindings=imported_assignments,
                )
            )
    return tuple(sorted(dependencies))


def _production_gate_calls_runner(
    root: Path,
    gate_id: str,
) -> bool:
    relative, separator, selector = gate_id.partition("::")
    if not separator:
        return False
    test_name = selector.split("[", 1)[0]
    path = root / relative
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    aliases = {
        item.asname or item.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module
        == "tools.guide_gates.run_task11_production_path_matrix"
        for item in node.names
        if item.name == "run_production_path_matrix"
    }
    cases_path_aliases = {
        item.asname or item.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module
        == "tools.guide_gates.run_task11_production_path_matrix"
        for item in node.names
        if item.name == "DEFAULT_CASES_PATH"
    }
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    function = functions.get(test_name)
    if (
        function is None
        or len(aliases) != 1
        or len(cases_path_aliases) != 1
    ):
        return False
    alias = next(iter(aliases))
    cases_path_alias = next(iter(cases_path_aliases))
    if alias in _function_rebound_names(
        function,
        imported_module=(
            "tools.guide_gates.run_task11_production_path_matrix"
        ),
        imported_symbol="run_production_path_matrix",
    ):
        return False
    if cases_path_alias in _function_rebound_names(
        function,
        imported_module=(
            "tools.guide_gates.run_task11_production_path_matrix"
        ),
        imported_symbol="DEFAULT_CASES_PATH",
    ):
        return False
    all_runner_calls = tuple(
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == alias
    )
    if len(all_runner_calls) != 1:
        return False
    cases_path_values = [
        keyword.value
        for keyword in all_runner_calls[0].keywords
        if keyword.arg == "cases_path"
    ]
    if (
        len(cases_path_values) != 1
        or not isinstance(cases_path_values[0], ast.Name)
        or cases_path_values[0].id != cases_path_alias
    ):
        return False
    def target_names(node: ast.AST) -> set[str]:
        if isinstance(node, ast.Name):
            return {node.id}
        if isinstance(node, (ast.Tuple, ast.List)):
            return {
                name
                for item in node.elts
                for name in target_names(item)
            }
        return set()

    def asserts_passed(statement: ast.stmt, result_name: str) -> bool:
        if not isinstance(statement, ast.Assert):
            return False
        test = statement.test
        return (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Is)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value is True
            and isinstance(test.left, ast.Attribute)
            and isinstance(test.left.value, ast.Name)
            and test.left.value.id == result_name
            and test.left.attr == "passed"
        )

    def is_safe_result_assertion(
        statement: ast.stmt,
        result_name: str,
    ) -> bool:
        if not isinstance(statement, ast.Assert):
            return False
        test = statement.test
        if (
            not isinstance(test, ast.Compare)
            or len(test.ops) != 1
            or not isinstance(test.ops[0], (ast.Eq, ast.Is))
            or len(test.comparators) != 1
            or not isinstance(test.comparators[0], ast.Constant)
            or not isinstance(test.comparators[0].value, (bool, int))
        ):
            return False
        left = test.left
        if (
            isinstance(left, ast.Attribute)
            and isinstance(left.value, ast.Name)
            and left.value.id == result_name
        ):
            return True
        return (
            isinstance(left, ast.Call)
            and isinstance(left.func, ast.Name)
            and left.func.id == "len"
            and len(left.args) == 1
            and not left.keywords
            and isinstance(left.args[0], ast.Attribute)
            and isinstance(left.args[0].value, ast.Name)
            and left.args[0].value.id == result_name
            and left.args[0].attr == "turn_traces"
        )

    def is_provider_env_cleanup(statement: ast.stmt) -> bool:
        if not isinstance(statement, ast.Expr):
            return False
        call = statement.value
        return (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "monkeypatch"
            and call.func.attr == "delenv"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value
            in {"GUIDE_LLM_API_KEY", "GUIDE_COPY_LLM_API_KEY"}
            and len(call.keywords) == 1
            and call.keywords[0].arg == "raising"
            and isinstance(call.keywords[0].value, ast.Constant)
            and call.keywords[0].value.value is False
        )

    calls: list[ast.Call] = []
    result_names: set[str] = set()
    result_asserted = False
    for statement in function.body:
        value = (
            statement.value
            if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.Expr))
            else None
        )
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == alias
        ):
            if (
                not result_names
                and not calls
                and is_provider_env_cleanup(statement)
            ):
                continue
            if (
                result_names
                and is_safe_result_assertion(
                    statement,
                    next(iter(result_names)),
                )
            ):
                result_asserted = (
                    result_asserted
                    or asserts_passed(
                        statement,
                        next(iter(result_names)),
                    )
                )
                continue
            return False
        if value.args or {
            keyword.arg for keyword in value.keywords
        } != {
            "repo_root",
            "cases_path",
            "state_root",
            "candidate_manifest_sha256",
            "protected_payload_sha256",
            "cases_sha256",
        }:
            return False
        calls.append(value)
        if isinstance(statement, ast.Assign):
            result_names.update(
                name
                for target in statement.targets
                for name in target_names(target)
            )
        elif isinstance(statement, ast.AnnAssign):
            result_names.update(target_names(statement.target))
    if len(calls) != 1 or len(result_names) != 1 or not result_asserted:
        return False
    result_name = next(iter(result_names))
    return (
        sum(
            1
            for node in ast.walk(function)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id == result_name
        )
        == 1
    )


def _validate_test_path(
    payload: Mapping[str, object],
    *,
    root: Path,
    manifest: Mapping[str, object],
) -> int:
    label = "test-path audit"
    _require(
        payload.get("schema_version")
        == "guide-task11-test-path-audit-v1",
        f"{label} schema is invalid",
    )
    _require(payload.get("passed") is True, f"{label} did not pass")
    _required_zero(
        payload,
        "invalid_production_path_claim_count",
        label=label,
    )
    _required_zero(
        payload,
        "unprotected_fixture_dependency_count",
        label=label,
    )
    gates = payload.get("gates")
    _require(isinstance(gates, list) and bool(gates), f"{label} gates missing")
    fixture_paths = set(manifest.get("fixture_paths", ()))
    test_paths = set(manifest.get("test_paths", ()))
    fixture_union: set[str] = set()
    production_gates: list[Mapping[str, object]] = []
    nonproduction_scopes: list[object] = []
    declared_nodes: list[str] = []
    declared_test_files: set[str] = set()
    declared_fixtures_by_node: dict[str, tuple[str, set[str]]] = {}
    allowed_scopes = {
        "unit",
        "layer_contract",
        "frontend_fixture",
        "production_path_from_turn_meaning",
    }
    for gate in gates:
        _require(isinstance(gate, dict), f"{label} gate is invalid")
        scope = gate.get("claimed_scope")
        _require(scope in allowed_scopes, f"{label} scope is invalid")
        gate_tests = gate.get("test_files")
        gate_fixtures = gate.get("fixture_files")
        _require(
            isinstance(gate_tests, list)
            and bool(gate_tests)
            and all(item in test_paths for item in gate_tests),
            f"{label} gate test files are not protected",
        )
        gate_id = gate.get("gate")
        _require(
            isinstance(gate_id, str) and "::" in gate_id,
            f"{label} gate node ID is invalid",
        )
        declared_nodes.append(gate_id)
        declared_test_files.update(str(item) for item in gate_tests)
        _require(
            isinstance(gate_fixtures, list)
            and all(item in fixture_paths for item in gate_fixtures),
            f"{label} gate fixture files are not protected",
        )
        if scope == "production_path_from_turn_meaning":
            _require(
                gate_fixtures == [PRODUCTION_MATRIX_FIXTURE_PATH],
                f"{label} production matrix fixture binding is invalid",
            )
        declared_fixtures_by_node[gate_id] = (
            str(gate_tests[0]),
            set(str(item) for item in gate_fixtures),
        )
        fixture_union.update(str(item) for item in gate_fixtures)
        if scope == "production_path_from_turn_meaning":
            production_gates.append(gate)
        else:
            nonproduction_scopes.append(scope)
            layers_executed = gate.get("layers_executed")
            if scope == "unit":
                _require(
                    gate.get("real_entrypoint") == "direct_component_api"
                    and layers_executed == ["isolated_component"]
                    and gate.get("layers_bypassed")
                    == [
                        "http_production_path",
                        "cross_layer_integration",
                    ]
                    and gate.get("semantic_injection_type")
                    == "direct_value_or_component",
                    f"{label} unit scope metadata is invalid",
                )
            elif scope == "frontend_fixture":
                _require(
                    gate.get("real_entrypoint")
                    == "prebuilt_frontend_fixture"
                    and layers_executed
                    == ["typed_sse_fixture", "frontend_renderer"]
                    and gate.get("layers_bypassed")
                    == ["live_backend", "http_production_path"]
                    and gate.get("semantic_injection_type")
                    == "prebuilt_typed_sse",
                    f"{label} frontend fixture scope metadata is invalid",
                )
            else:
                _require(
                    gate.get("real_entrypoint")
                    == "direct_layer_boundary"
                    and isinstance(layers_executed, list)
                    and bool(layers_executed)
                    and gate.get("layers_bypassed")
                    == ["full_http_production_path"]
                    and gate.get("semantic_injection_type")
                    == "direct_contract_or_component",
                    f"{label} layer scope metadata is invalid",
                )
    _require(
        len(production_gates) == 1
        and _required_int(
            payload,
            "production_path_gate_count",
            label=label,
        )
        == 1,
        f"{label} must contain one authorizing production gate",
    )
    _require(
        bool(nonproduction_scopes)
        and set(nonproduction_scopes) != {"layer_contract"},
        f"{label} uses a catch-all non-production scope",
    )
    scope_counts = payload.get("scope_counts")
    derived_scope_counts = {
        scope: sum(
            gate.get("claimed_scope") == scope
            for gate in gates
        )
        for scope in sorted(allowed_scopes)
    }
    _require(
        scope_counts == derived_scope_counts,
        f"{label} scope counts are invalid",
    )
    gate = production_gates[0]
    layers = gate.get("layers_executed")
    _require(
        gate.get("real_entrypoint") == "/api/v1/chat/stream"
        and gate.get("layers_bypassed") == []
        and gate.get("semantic_injection_type")
        == "frozen_turn_meaning_provider"
        and layers == RUNTIME_LAYER_ORDER
        and gate.get("runtime_evidence_source")
        == "task11-production-path-summary",
        f"{label} runtime evidence source or frozen provider is invalid",
    )
    _require(
        gate.get("fixture_files") == [PRODUCTION_MATRIX_FIXTURE_PATH],
        f"{label} production matrix fixture binding is invalid",
    )
    expected_counts = {
        "case_count": PRODUCTION_MATRIX_TURN_COUNT,
        "trajectory_count": 12,
        "turn_count": PRODUCTION_MATRIX_TURN_COUNT,
        "state_edge_count": 40,
        "pre_decision_rejection_count": PRE_DECISION_REJECTION_COUNT,
    }
    for key, expected in expected_counts.items():
        _require(
            _required_int(gate, key, label=label) == expected,
            f"{label} production gate field {key} is invalid",
        )
    dependencies = payload.get("fixture_dependencies")
    _require(
        isinstance(dependencies, list)
        and dependencies == sorted(set(dependencies))
        and set(dependencies) == fixture_paths
        and fixture_union <= set(dependencies),
        f"{label} fixture dependency inventory is invalid",
    )
    collected_nodes = _collect_pytest_nodes(
        root,
        tuple(sorted(declared_test_files)),
    )
    _require(
        tuple(sorted(declared_nodes)) == tuple(sorted(collected_nodes)),
        "pytest node inventory does not match the test-path audit",
    )
    for gate_id, (
        test_file,
        declared_fixtures,
    ) in sorted(declared_fixtures_by_node.items()):
        discovered_fixtures = set(
            _test_node_fixture_dependencies(
                root / test_file,
                node_id=gate_id,
                repo_root=root,
            )
        )
        _require(
            discovered_fixtures == declared_fixtures,
            f"{label} independently discovered fixtures differ for "
            f"{gate_id}",
        )
    _require(
        _production_gate_calls_runner(root, str(gate["gate"])),
        f"{label} production gate does not call the canonical runner",
    )
    return len(collected_nodes)


def _trace_digest(
    trace: Mapping[str, object],
    names: Sequence[str],
    *,
    label: str,
) -> str:
    for name in names:
        if name in trace:
            value = trace[name]
            _require(_is_digest(value), f"{label} field {name} is invalid")
            return str(value)
    raise Task11IndependentAuditError(
        f"{label} is missing digest field {names[0]}"
    )


def _validate_pre_decision_rejection_trace(
    trace: Mapping[str, object],
    *,
    index: int,
) -> set[str]:
    label = f"production trace {index}"
    _require(
        trace.get("rejection_stage") == "pre_decision",
        f"{label} pre-decision rejection stage is invalid",
    )
    zero_count_fields = (
        "translation_injection_count",
        "structured_understanding_injection_count",
        "compiler_call_count",
        "direct_router_bypass_count",
        "legacy_entrypoint_count",
        "router_call_count",
        "execution_result_count",
        "reducer_call_count",
        "state_save_count",
        "state_save_completed_count",
        "selected_processor_instance_entry_count",
        "unregistered_processor_invocation_count",
        "decision_identity_violation_count",
        "processor_state_write_count",
        "event_state_projection_count",
        "provider_call_count",
        "outbound_network_attempt_count",
    )
    for key in zero_count_fields:
        _required_zero(trace, key, label=label)
    decision_digests = {
        _trace_digest(
            trace,
            ("route_decision_digest",),
            label=label,
        ),
        _trace_digest(
            trace,
            ("selected_processor_decision_digest",),
            label=label,
        ),
        _trace_digest(
            trace,
            ("result_decision_digest",),
            label=label,
        ),
        _trace_digest(
            trace,
            ("sse_decision_digest", "emitted_decision_digest"),
            label=label,
        ),
    }
    _require(
        decision_digests == {"0" * 64},
        f"{label} pre-decision rejection fabricated a decision",
    )
    validated_bytes = _trace_digest(
        trace,
        ("validated_sse_sha256",),
        label=label,
    )
    emitted_bytes = _trace_digest(
        trace,
        ("emitted_sse_sha256",),
        label=label,
    )
    _require(
        validated_bytes == emitted_bytes,
        f"{label} pre-decision rejection bytes are unstable",
    )
    invocation_counts = trace.get("processor_invocation_counts")
    _require(
        trace.get("selected_processor") == "none"
        and trace.get("actual_processor") == "none"
        and isinstance(invocation_counts, dict)
        and all(
            isinstance(name, str)
            and bool(name)
            and _is_int(count)
            and int(count) == 0
            for name, count in invocation_counts.items()
        )
        and trace.get("processor_implementation_counts") == {},
        f"{label} pre-decision rejection invoked a processor",
    )
    _require(
        trace.get("accepted") is False
        and trace.get("terminal_event") == "error"
        and trace.get("semantic_equivalence_passed") is True
        and trace.get("event_names") == ["start", "error"]
        and trace.get("coverage_edges") == []
        and trace.get("card_ids") == []
        and trace.get("bounded") is False,
        f"{label} pre-decision rejection terminal contract is invalid",
    )
    loaded = _required_int(trace, "loaded_version", label=label)
    committed = _required_int(trace, "committed_version", label=label)
    _require(
        loaded >= 0 and committed == loaded,
        f"{label} pre-decision rejection mutated state",
    )
    _require(
        trace.get("expected_state_edge") == trace.get("observed_state_edge")
        and isinstance(trace.get("expected_state_edge"), str)
        and bool(trace["expected_state_edge"]),
        f"{label} pre-decision rejection state edge is invalid",
    )
    return set()


def _validate_trace(trace: object, *, index: int) -> set[str]:
    label = f"production trace {index}"
    _require(isinstance(trace, dict), f"{label} is invalid")
    turn_id = trace.get("turn_id")
    trajectory_id = trace.get("trajectory_id")
    partition = trace.get("partition")
    _require(
        isinstance(turn_id, str)
        and bool(turn_id)
        and isinstance(trajectory_id, str)
        and bool(trajectory_id)
        and partition
        in {"semantic", "state", "bounded", "pre_decision_rejection"},
        f"{label} identity is invalid",
    )
    if partition == "pre_decision_rejection":
        return _validate_pre_decision_rejection_trace(
            trace,
            index=index,
        )
    expected_counts = {
        "translation_injection_count": 1,
        "compiler_call_count": 1,
        "router_call_count": 1,
        "execution_result_count": 1,
        "reducer_call_count": 1,
        "state_save_count": 1,
        "state_save_completed_count": 1,
    }
    for key, expected in expected_counts.items():
        _require(
            _required_int(trace, key, label=label) == expected,
            f"{label} field {key} is invalid",
        )
    for key in TRACE_ZERO_FIELDS:
        _required_zero(trace, key, label=label)
    route_digest = _trace_digest(
        trace,
        ("route_decision_digest",),
        label=label,
    )
    selected_digest = _trace_digest(
        trace,
        (
            "selected_processor_decision_digest",
            "processor_decision_digest",
        ),
        label=label,
    )
    result_digest = _trace_digest(
        trace,
        ("result_decision_digest",),
        label=label,
    )
    sse_digest = _trace_digest(
        trace,
        ("sse_decision_digest", "emitted_decision_digest"),
        label=label,
    )
    _require(
        len({route_digest, selected_digest, result_digest, sse_digest}) == 1,
        f"{label} decision identity is inconsistent",
    )
    byte_pairs = (
        ("validated_sse_sha256", "emitted_sse_sha256"),
        ("validated_envelope_sha256", "emitted_envelope_sha256"),
        ("validated_frames_sha256", "emitted_frames_sha256"),
    )
    matched_pair = next(
        (
            pair
            for pair in byte_pairs
            if pair[0] in trace or pair[1] in trace
        ),
        None,
    )
    _require(matched_pair is not None, f"{label} emitted-byte proof is missing")
    validated_bytes = _trace_digest(trace, (matched_pair[0],), label=label)
    emitted_bytes = _trace_digest(trace, (matched_pair[1],), label=label)
    _require(
        validated_bytes == emitted_bytes,
        f"{label} emitted bytes differ from validated bytes",
    )

    selected = trace.get("selected_processor", trace.get("actual_processor"))
    counts = trace.get(
        "processor_invocation_counts",
        trace.get("processor_invocation_count_by_name"),
    )
    implementation_counts = trace.get(
        "processor_implementation_counts"
    )
    _require(
        isinstance(selected, str)
        and bool(selected)
        and isinstance(counts, dict)
        and bool(counts),
        f"{label} processor invocation evidence is missing",
    )
    _require(
        all(
            isinstance(name, str)
            and bool(name)
            and _is_int(count)
            and int(count) >= 0
            for name, count in counts.items()
        ),
        f"{label} processor invocation evidence is invalid",
    )
    _require(
        counts.get(selected) == 1
        and all(count == 0 for name, count in counts.items() if name != selected),
        f"{label} selected processor invocation count is invalid",
    )
    _require(
        isinstance(implementation_counts, dict)
        and bool(implementation_counts)
        and all(
            isinstance(name, str)
            and bool(name)
            and _is_int(count)
            and int(count) >= 0
            for name, count in implementation_counts.items()
        )
        and sum(int(count) for count in implementation_counts.values()) == 1,
        f"{label} concrete processor implementation evidence is invalid",
    )
    _require(
        _required_int(
            trace,
            "selected_processor_instance_entry_count",
            label=label,
        )
        == 1
        and _required_int(
            trace,
            "unregistered_processor_invocation_count",
            label=label,
        )
        == 0,
        f"{label} processor instance evidence is invalid",
    )
    _require(
        trace.get("state_backend") == "SqliteConversationState",
        f"{label} state backend is not SQLite",
    )
    _require(
        trace.get("observed_layers") == RUNTIME_LAYER_ORDER,
        f"{label} observed runtime layers are invalid",
    )
    _require(
        trace.get("accepted") is True
        and trace.get("terminal_event") == "end"
        and trace.get("semantic_equivalence_passed") is True,
        f"{label} did not complete successfully",
    )
    loaded = _required_int(trace, "loaded_version", label=label)
    committed = _required_int(trace, "committed_version", label=label)
    _require(
        loaded >= 0 and committed == loaded + 1,
        f"{label} state version transition is invalid",
    )
    _require(
        trace.get("expected_state_edge") == trace.get("observed_state_edge")
        and isinstance(trace.get("expected_state_edge"), str)
        and bool(trace["expected_state_edge"]),
        f"{label} state transition is invalid",
    )
    _require(
        trace.get("bounded") is (partition == "bounded"),
        f"{label} bounded marker is invalid",
    )
    coverage = trace.get("coverage_edges")
    _require(
        isinstance(coverage, list)
        and len(coverage) == len(set(coverage))
        and all(isinstance(edge, str) and edge for edge in coverage),
        f"{label} observed coverage edges are invalid",
    )
    return set(coverage)


def _matrix_case_coverage(
    case: Mapping[str, object],
    *,
    index: int,
) -> tuple[list[str] | None, set[str]]:
    label = f"production matrix case {index}"
    required = case.get("required_state_edges") or []
    _require(
        isinstance(required, list)
        and len(required) == len(set(required))
        and all(isinstance(edge, str) and edge for edge in required),
        f"{label} required coverage is invalid",
    )
    expected = case.get("expected_coverage")
    if expected is None:
        _require(
            not required,
            f"{label} requires coverage without an expected point",
        )
        return None, set()
    dimensions = (
        "active_owner",
        "reply_state",
        "preserved_authority",
        "semantic_act",
        "reference_source",
    )
    _require(
        isinstance(expected, dict)
        and set(expected) == set(dimensions)
        and all(
            isinstance(expected.get(name), str)
            and bool(expected[name])
            for name in dimensions
        ),
        f"{label} expected coverage point is invalid",
    )
    edges = [
        (
            f"{left}={expected[left]}|"
            f"{right}={expected[right]}"
        )
        for left_index, left in enumerate(dimensions)
        for right in dimensions[left_index + 1 :]
    ]
    _require(
        set(required).issubset(edges),
        f"{label} required coverage is outside its expected point",
    )
    return edges, set(required)


def _validate_production_summary(
    payload: Mapping[str, object],
    *,
    candidate_manifest_sha256: str,
    protected_payload_sha256: str,
    cases_path: Path,
) -> None:
    label = "production-path summary"
    try:
        cases = [
            json.loads(line)
            for line in cases_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Task11IndependentAuditError(
            f"{label} matrix fixture is invalid"
        ) from exc
    pre_decision_cases = [
        case
        for case in cases
        if (
            isinstance(case, dict)
            and case.get("partition") == "pre_decision_rejection"
        )
    ]
    _require(
        len(cases) == PRODUCTION_MATRIX_TURN_COUNT
        and all(isinstance(case, dict) for case in cases),
        f"{label} matrix fixture must contain "
        f"{PRODUCTION_MATRIX_TURN_COUNT} object rows",
    )
    _require(
        len(pre_decision_cases) == PRE_DECISION_REJECTION_COUNT
        and pre_decision_cases[0].get("conversation_version_delta") != 0
        and pre_decision_cases[0].get("expected_terminal_event")
        == "error"
        and pre_decision_cases[0].get("expected_rejection_stage")
        == "pre_decision",
        f"{label} pre-decision rejection fixture coverage is invalid",
    )
    _require(
        payload.get("schema_version")
        == "guide-task11-production-path-summary-v1",
        f"{label} schema is invalid",
    )
    _require(
        payload.get("candidate_manifest_sha256")
        == candidate_manifest_sha256
        and payload.get("protected_payload_sha256")
        == protected_payload_sha256
        and payload.get("cases_sha256") == _digest_file(cases_path),
        f"{label} candidate binding is invalid",
    )
    _require(payload.get("passed") is True, f"{label} did not pass")
    traces = payload.get("turn_traces")
    _require(
        isinstance(traces, list)
        and len(traces) == PRODUCTION_MATRIX_TURN_COUNT,
        f"{label} must contain {PRODUCTION_MATRIX_TURN_COUNT} turn traces",
    )
    turn_ids: set[str] = set()
    semantic_count = 0
    stateful_count = 0
    bounded_count = 0
    pre_decision_rejection_count = 0
    stateful_trajectories: set[str] = set()
    observed_edges: set[str] = set()
    committed_version_by_trajectory: dict[str, int] = {}
    for index, (trace, case) in enumerate(
        zip(traces, cases, strict=True)
    ):
        coverage = _validate_trace(trace, index=index)
        _require(isinstance(trace, dict), f"{label} trace is invalid")
        trajectory_id = str(trace["trajectory_id"])
        expected_loaded_version = committed_version_by_trajectory.get(
            trajectory_id,
            0,
        )
        _require(
            trace.get("loaded_version") == expected_loaded_version,
            f"{label} trajectory state continuity is invalid",
        )
        committed_version_by_trajectory[trajectory_id] = int(
            trace["committed_version"]
        )
        expected_processor = case.get("expected_processor")
        expected_intent = case.get("expected_intent")
        expected_cards = case.get("expected_card_ids")
        expected_coverage, required_coverage = _matrix_case_coverage(
            case,
            index=index,
        )
        _require(
            trace.get("turn_id") == case.get("case_id")
            and trace.get("trajectory_id") == case.get("trajectory_id")
            and trace.get("partition") == case.get("partition")
            and trace.get("bounded") is case.get("bounded")
            and trace.get("expected_state_edge")
            == case.get("expected_state_edge")
            and (
                expected_coverage is None
                or trace.get("coverage_edges") == expected_coverage
            )
            and required_coverage <= coverage
            and (
                expected_processor is None
                or trace.get("actual_processor") == expected_processor
            )
            and (
                expected_intent is None
                or trace.get("actual_intent") == expected_intent
            )
            and (
                expected_cards is None
                or trace.get("card_ids") == expected_cards
            ),
            f"{label} trace {index} disagrees with matrix expectation",
        )
        turn_id = str(trace["turn_id"])
        _require(turn_id not in turn_ids, f"{label} has duplicate turn IDs")
        turn_ids.add(turn_id)
        if trace["partition"] == "semantic":
            semantic_count += 1
        elif trace["partition"] in {"state", "bounded"}:
            stateful_count += 1
            stateful_trajectories.add(str(trace["trajectory_id"]))
            observed_edges.update(coverage)
        else:
            pre_decision_rejection_count += 1
        if trace["partition"] == "bounded":
            bounded_count += 1
    expected_counts = {
        "expected_contract_case_count": 128,
        "actual_equivalence_case_count": semantic_count,
        "trajectory_count": len(stateful_trajectories),
        "stateful_turn_count": stateful_count,
        "turn_count": len(traces),
        "state_edge_count": 40,
        "required_state_edge_count": 40,
        "bounded_turn_count": bounded_count,
        "pre_decision_rejection_count": pre_decision_rejection_count,
        "pre_decision_rejection_failure_count": 0,
        "translation_injection_count": PRODUCTION_ACCEPTED_TURN_COUNT,
    }
    _require(
        semantic_count == 128
        and stateful_count == 48
        and len(stateful_trajectories) == 12
        and bounded_count == 9
        and pre_decision_rejection_count
        == PRE_DECISION_REJECTION_COUNT
        and len(observed_edges) >= 40,
        f"{label} derived coverage counts are invalid",
    )
    _require(
        payload.get("pre_decision_rejection_count")
        == PRE_DECISION_REJECTION_COUNT
        and payload.get("pre_decision_rejection_failure_count") == 0,
        f"{label} pre-decision rejection coverage is invalid",
    )
    for key, expected in expected_counts.items():
        _require(
            _required_int(payload, key, label=label) == expected,
            f"{label} field {key} is inconsistent",
        )
    required_edges = payload.get("required_state_edges")
    fixture_edges = sorted({
        edge
        for case in cases
        for edge in case.get("required_state_edges", ())
    })
    _require(
        isinstance(required_edges, list)
        and len(required_edges) == 40
        and len(required_edges) == len(set(required_edges))
        and set(required_edges) <= observed_edges
        and required_edges == fixture_edges,
        f"{label} required state edge inventory is invalid",
    )
    _require(
        payload.get("observed_layers") == RUNTIME_LAYER_ORDER,
        f"{label} observed runtime layers are invalid",
    )
    for key in SUMMARY_ZERO_FIELDS:
        _required_zero(payload, key, label=label)


def _sse_events(raw: str, *, label: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        event_name: str | None = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                _require(
                    event_name is None,
                    f"{label} contains duplicate event fields",
                )
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
            elif line.strip():
                raise Task11IndependentAuditError(
                    f"{label} contains an unsupported SSE field"
                )
        if event_name is None and not data_lines:
            continue
        _require(
            event_name is not None and bool(data_lines),
            f"{label} contains an incomplete SSE event",
        )
        try:
            data = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise Task11IndependentAuditError(
                f"{label} contains invalid SSE JSON"
            ) from exc
        _require(isinstance(data, dict), f"{label} SSE data is not an object")
        events.append((event_name, data))
    return events


def _artifact_index(payload: Mapping[str, object]) -> dict[str, str]:
    raw = payload.get(
        "artifact_sha256",
        payload.get("artifact_sha256_by_path"),
    )
    _require(
        isinstance(raw, dict) and bool(raw),
        "browser summary artifact hash index is missing",
    )
    result: dict[str, str] = {}
    for key, value in raw.items():
        relative = _relative_path(key, label="browser artifact path")
        _require(
            _is_digest(value),
            f"browser artifact hash is invalid: {relative}",
        )
        result[relative] = str(value)
    return result


def _validate_seatbelt_audit(
    *,
    root: Path,
    summary: Mapping[str, object],
    label: str,
) -> bytes:
    sandbox_path = root / "sandbox-audit.json"
    raw_path = root / "seatbelt.raw.ndjson"
    profile_path = root / "sandbox-profile.sb"
    netlog_path = root / "chromium-netlog.json"
    sandbox = _load_object(
        sandbox_path,
        label=f"{label} Seatbelt audit",
    )
    _require(
        sandbox.get("schema_version")
        == "guide-fixture-browser-sandbox-audit-v2"
        and sandbox.get("passed") is True
        and sandbox.get("enforcement")
        == "macos-sandbox-exec-loopback-only"
        and sandbox.get("measurement")
        == "macos-unified-log-seatbelt-kernel",
        f"{label} Seatbelt measurement is invalid",
    )
    nonce = sandbox.get("measurement_nonce")
    _require(
        isinstance(nonce, str) and HEX_64.fullmatch(nonce) is not None,
        f"{label} Seatbelt nonce is invalid",
    )
    profile = profile_path.read_text(encoding="utf-8")
    expected_profile = (
        "(version 1)"
        "(allow default)"
        "(deny network-outbound "
        "(with telemetry) "
        f"(with message \"{nonce}\"))"
        "(allow network-outbound (remote ip \"localhost:*\"))"
        "(allow network-inbound)"
    )
    profile_digest = _digest_file(profile_path)
    _require(
        profile == expected_profile
        and sandbox.get("sandbox_profile_sha256") == profile_digest
        and sandbox.get("sandbox_identity")
        == f"macos-sandbox-exec-loopback-only:{profile_digest}"
        and summary.get("sandbox_identity")
        == sandbox.get("sandbox_identity"),
        f"{label} Seatbelt profile binding is invalid",
    )
    raw = raw_path.read_bytes()
    raw_digest = sha256(raw).hexdigest()
    _require(
        sandbox.get("seatbelt_raw_ndjson_sha256") == raw_digest
        and summary.get("seatbelt_raw_ndjson_sha256") == raw_digest,
        f"{label} Seatbelt raw log hash is invalid",
    )
    _require(
        sandbox.get("seatbelt_raw_byte_count") == len(raw)
        and sandbox.get("logger_ready") is True
        and sandbox.get("logger_loss_event_count") == 0
        and sandbox.get("logger_returncode") in {0, 130, -2},
        f"{label} Seatbelt logger health is invalid",
    )
    _require(
        sandbox.get("netlog_sha256") == _digest_file(netlog_path),
        f"{label} Chromium netlog hash is invalid",
    )
    events: list[dict[str, object]] = []
    try:
        raw_text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise Task11IndependentAuditError(
            f"{label} Seatbelt raw log is not UTF-8"
        ) from exc
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Task11IndependentAuditError(
                f"{label} Seatbelt raw log is malformed"
            ) from exc
        _require(
            isinstance(event, dict),
            f"{label} Seatbelt raw event is invalid",
        )
        event["_line_number"] = line_number
        events.append(event)
    _require(
        sandbox.get("seatbelt_event_count") == len(events)
        and not any(
            event.get("eventType") == "lossEvent"
            for event in events
        ),
        f"{label} Seatbelt logger lost events",
    )
    ready = f"XIAORO_SEATBELT_READY:{nonce}"
    begin_pattern = re.compile(
        rf"^XIAORO_SEATBELT_BEGIN:{nonce}:(\d+)$"
    )
    root_child_pattern = re.compile(
        rf"^XIAORO_SEATBELT_CANARY:{nonce}:root_child:(\d+):9$"
    )
    descendant_pattern = re.compile(
        rf"^XIAORO_SEATBELT_CANARY:{nonce}:descendant:(\d+):443$"
    )
    end_pattern = re.compile(
        rf"^XIAORO_SEATBELT_END:{nonce}:(\d+)$"
    )
    drain_marker = f"XIAORO_SEATBELT_DRAIN:{nonce}"
    drain_canary_pattern = re.compile(
        rf"^XIAORO_SEATBELT_CANARY:{nonce}:drain:(\d+):53$"
    )

    def marker_indexes(
        pattern: re.Pattern[str] | str,
    ) -> list[tuple[int, re.Match[str] | None]]:
        found: list[tuple[int, re.Match[str] | None]] = []
        for index, event in enumerate(events):
            if event.get("processImagePath") != "/usr/bin/logger":
                continue
            message = event.get("eventMessage")
            if not isinstance(message, str):
                continue
            if isinstance(pattern, str):
                if message == pattern:
                    found.append((index, None))
            else:
                match = pattern.fullmatch(message)
                if match is not None:
                    found.append((index, match))
        return found

    ready_rows = marker_indexes(ready)
    begin_rows = marker_indexes(begin_pattern)
    root_child_rows = marker_indexes(root_child_pattern)
    descendant_rows = marker_indexes(descendant_pattern)
    end_rows = marker_indexes(end_pattern)
    drain_canary_rows = marker_indexes(drain_canary_pattern)
    drain_rows = marker_indexes(drain_marker)
    _require(
        len(ready_rows) >= 1
        and len(begin_rows) == len(root_child_rows)
        == len(descendant_rows) == len(end_rows)
        == len(drain_canary_rows) == len(drain_rows) == 1
        and sandbox.get("logger_readiness_marker_count")
        == len(ready_rows),
        f"{label} Seatbelt marker inventory is invalid",
    )
    begin_match = begin_rows[0][1]
    root_child_match = root_child_rows[0][1]
    descendant_match = descendant_rows[0][1]
    end_match = end_rows[0][1]
    drain_canary_match = drain_canary_rows[0][1]
    _require(
        begin_match is not None
        and root_child_match is not None
        and descendant_match is not None
        and end_match is not None
        and drain_canary_match is not None,
        f"{label} Seatbelt marker identity is invalid",
    )
    root_pid = int(begin_match.group(1))
    root_child_pid = int(root_child_match.group(1))
    descendant_pid = int(descendant_match.group(1))
    drain_canary_pid = int(drain_canary_match.group(1))
    _require(
        root_pid == int(end_match.group(1))
        and sandbox.get("sandbox_process_group_id") == root_pid
        and sandbox.get("process_group_quiescent") is True
        and root_child_pid not in {root_pid, descendant_pid}
        and descendant_pid != root_pid
        and drain_canary_pid not in {
            root_pid,
            root_child_pid,
            descendant_pid,
        }
        and ready_rows[0][0] < begin_rows[0][0]
        < root_child_rows[0][0] < descendant_rows[0][0]
        < drain_canary_rows[0][0] < end_rows[0][0]
        < drain_rows[0][0]
        and sandbox.get("root_pid") == root_pid
        and sandbox.get("root_child_canary_pid") == root_child_pid
        and sandbox.get("descendant_canary_pid") == descendant_pid
        and sandbox.get("drain_canary_pid") == drain_canary_pid,
        f"{label} Seatbelt marker order, PID, or process group is invalid",
    )
    denial_pattern = re.compile(
        r"^Sandbox: (?P<process>.+)\((?P<pid>\d+)\) deny\(1\) "
        r"network-outbound remote:\*:(?P<port>\d+)\n"
        rf"{nonce}$"
    )
    duplicate_denial_pattern = re.compile(
        r"^(?P<count>\d+) duplicate reports? for Sandbox: "
        r"(?P<process>.+)\((?P<pid>\d+)\) deny\(1\) "
        r"network-outbound remote:\*:(?P<port>\d+)\n"
        rf"{nonce}$"
    )
    denials: list[dict[str, object]] = []
    duplicate_denials: list[dict[str, object]] = []
    for event in events:
        if (
            event.get("processImagePath") != "/kernel"
            or event.get("senderImagePath")
            != (
                "/System/Library/Extensions/Sandbox.kext/"
                "Contents/MacOS/Sandbox"
            )
        ):
            continue
        message = event.get("eventMessage")
        if not isinstance(message, str):
            continue
        match = denial_pattern.fullmatch(message)
        if match is None:
            duplicate_match = duplicate_denial_pattern.fullmatch(message)
            if duplicate_match is not None:
                duplicate_denials.append({
                    "count": int(duplicate_match.group("count")),
                    "process": duplicate_match.group("process"),
                    "pid": int(duplicate_match.group("pid")),
                    "port": int(duplicate_match.group("port")),
                    "line_number": event["_line_number"],
                })
                continue
        _require(
            match is not None or nonce not in message,
            f"{label} Seatbelt denial event is malformed",
        )
        if match is not None:
            denials.append({
                "process": match.group("process"),
                "pid": int(match.group("pid")),
                "port": int(match.group("port")),
                "line_number": event["_line_number"],
            })
    root_denials = [
        item for item in denials
        if item["pid"] == root_child_pid and item["port"] == 9
    ]
    child_denials = [
        item for item in denials
        if item["pid"] == descendant_pid and item["port"] == 443
    ]
    drain_denials = [
        item for item in denials
        if item["pid"] == drain_canary_pid and item["port"] == 53
    ]
    root_denial_index = (
        int(root_denials[0]["line_number"]) - 1
        if len(root_denials) == 1
        else -1
    )
    child_denial_index = (
        int(child_denials[0]["line_number"]) - 1
        if len(child_denials) == 1
        else -1
    )
    drain_denial_index = (
        int(drain_denials[0]["line_number"]) - 1
        if len(drain_denials) == 1
        else -1
    )
    _require(
        len(root_denials) == 1
        and len(child_denials) == 1
        and len(drain_denials) == 1
        and begin_rows[0][0]
        < root_denial_index
        < child_denial_index
        < root_child_rows[0][0]
        < descendant_rows[0][0]
        and drain_canary_rows[0][0]
        < drain_denial_index
        < end_rows[0][0]
        < drain_rows[0][0],
        f"{label} Seatbelt canary delivery order is invalid",
    )
    canary_lines = {
        root_denials[0]["line_number"],
        child_denials[0]["line_number"],
        drain_denials[0]["line_number"],
    }
    _, netlog_attempts = _chromium_netlog_evidence(
        netlog_path,
        label=label,
    )
    known_probe_only = all(
        item["target"] == CHROMIUM_IPV6_PROBE_TARGET
        and item["event_type"] in {46, 94}
        for item in netlog_attempts
    )
    _require(
        not netlog_attempts or known_probe_only,
        f"{label} Chromium netlog contains a non-loopback target",
    )
    probe_denials = [
        item
        for item in denials
        if (
            item["process"] == "chrome-headless-shell"
            and item["port"] == 443
            and item["line_number"] not in canary_lines
        )
    ]
    probe_duplicate_denials = [
        item
        for item in duplicate_denials
        if (
            item["process"] == "chrome-headless-shell"
            and item["port"] == 443
        )
    ]
    environmental_probe_attempts = (
        bool(netlog_attempts)
        and bool(probe_denials or probe_duplicate_denials)
        and known_probe_only
    )
    _require(
        not environmental_probe_attempts
        or all(
            begin_rows[0][0]
            < int(item["line_number"]) - 1
            < end_rows[0][0]
            for item in (*probe_denials, *probe_duplicate_denials)
        ),
        f"{label} Chromium probe denial order is invalid",
    )
    allowed_duplicate_keys = {
        (root_child_pid, 9),
        (descendant_pid, 443),
        (drain_canary_pid, 53),
    }
    if environmental_probe_attempts:
        allowed_duplicate_keys.update(
            (int(item["pid"]), int(item["port"]))
            for item in probe_denials
        )
        allowed_duplicate_keys.update(
            (int(item["pid"]), int(item["port"]))
            for item in probe_duplicate_denials
        )
    _require(
        all(
            (int(item["pid"]), int(item["port"]))
            in allowed_duplicate_keys
            for item in duplicate_denials
        ),
        f"{label} Seatbelt denial event is malformed",
    )
    process_tree_attempts = [
        item
        for item in denials
        if (
            item["line_number"] not in canary_lines
            and not (
                environmental_probe_attempts
                and item in probe_denials
            )
        )
    ]
    if not environmental_probe_attempts:
        process_tree_attempts.extend(
            {
                "source": "chromium_netlog",
                **item,
            }
            for item in netlog_attempts
        )
    _require(
        sandbox.get("seatbelt_canary_denial_count") == 3
        and sandbox.get("canary_denials")
        == [root_denials[0], child_denials[0], drain_denials[0]]
        and sandbox.get("blocked_environmental_probe_count")
        == (len(netlog_attempts) if environmental_probe_attempts else 0)
        and sandbox.get("blocked_environmental_probe_duplicate_count")
        == (
            len(probe_duplicate_denials)
            if environmental_probe_attempts
            else 0
        )
        and sandbox.get("blocked_environmental_probe_targets")
        == (
            [CHROMIUM_IPV6_PROBE_TARGET]
            if environmental_probe_attempts
            else []
        )
        and process_tree_attempts == []
        and sandbox.get("attempts") == [],
        f"{label} Seatbelt canary evidence is invalid",
    )
    return sandbox_path.read_bytes()


def _validate_png(
    path: Path,
    *,
    viewport: str,
    label: str,
) -> None:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_SCREENSHOT_FILE_BYTES + 1)
    except OSError as exc:
        raise Task11IndependentAuditError(
            f"{label} PNG is unreadable"
        ) from exc
    _require(
        len(raw) <= MAX_SCREENSHOT_FILE_BYTES
        and raw.startswith(b"\x89PNG\r\n\x1a\n"),
        f"{label} PNG signature is invalid",
    )
    offset = 8
    width = height = None
    bit_depth = color_type = compression = filter_method = interlace = None
    compressed = bytearray()
    saw_idat = False
    saw_iend = False
    while offset < len(raw):
        _require(
            offset + 12 <= len(raw),
            f"{label} PNG chunk is truncated",
        )
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        kind = raw[offset + 4 : offset + 8]
        end = offset + 12 + length
        _require(end <= len(raw), f"{label} PNG chunk is truncated")
        data = raw[offset + 8 : offset + 8 + length]
        checksum = struct.unpack(
            ">I",
            raw[offset + 8 + length : end],
        )[0]
        _require(
            checksum == (zlib.crc32(kind + data) & 0xFFFFFFFF),
            f"{label} PNG checksum is invalid",
        )
        if kind == b"IHDR":
            _require(
                width is None and length == 13 and offset == 8,
                f"{label} PNG header is invalid",
            )
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            _require(
                width is not None,
                f"{label} PNG IDAT order is invalid",
            )
            saw_idat = saw_idat or bool(data)
            compressed.extend(data)
        elif kind == b"IEND":
            _require(
                length == 0 and width is not None and not saw_iend,
                f"{label} PNG end chunk is invalid",
            )
            saw_iend = True
            offset = end
            break
        offset = end
    expected_width, minimum_height = (
        (1440, 1000) if viewport == "desktop" else (390, 844)
    )
    _require(
        width == expected_width
        and isinstance(height, int)
        and height >= minimum_height
        and height <= MAX_SCREENSHOT_HEIGHT
        and width <= MAX_SCREENSHOT_WIDTH
        and width * height <= MAX_SCREENSHOT_PIXELS
        and bit_depth == 8
        and color_type == 2
        and compression == 0
        and filter_method == 0
        and interlace == 0
        and saw_idat
        and saw_iend
        and offset == len(raw),
        f"{label} PNG dimensions or structure are invalid",
    )

    scanline_size = 1 + width * 3
    prior_row = bytes(width * 3)
    buffered = bytearray()
    compressed_input = bytes(compressed)
    histogram = [0] * 4096
    minimum_channels = [255, 255, 255]
    maximum_channels = [0, 0, 0]
    decoder = zlib.decompressobj()

    def paeth_prediction(
        left: int,
        above: int,
        upper_left: int,
    ) -> int:
        estimate = left + above - upper_left
        left_error = abs(estimate - left)
        above_error = abs(estimate - above)
        upper_left_error = abs(estimate - upper_left)
        if left_error <= above_error and left_error <= upper_left_error:
            return left
        if above_error <= upper_left_error:
            return above
        return upper_left

    try:
        for _ in range(height):
            while len(buffered) < scanline_size:
                compressed_size_before = len(compressed_input)
                decoded = decoder.decompress(
                    compressed_input,
                    scanline_size - len(buffered),
                )
                buffered.extend(decoded)
                compressed_input = decoder.unconsumed_tail
                _require(
                    bool(decoded)
                    or len(compressed_input) < compressed_size_before,
                    f"{label} PNG scanlines are invalid",
                )
                _require(
                    len(buffered) == scanline_size or bool(compressed_input),
                    f"{label} PNG scanlines are invalid",
                )
            row_filter = buffered[0]
            _require(
                row_filter <= 4,
                f"{label} PNG scanlines are invalid",
            )
            row = bytearray(buffered[1:])
            buffered.clear()
            for index, encoded in enumerate(row):
                left = row[index - 3] if index >= 3 else 0
                above = prior_row[index]
                upper_left = prior_row[index - 3] if index >= 3 else 0
                prediction = (
                    0
                    if row_filter == 0
                    else left
                    if row_filter == 1
                    else above
                    if row_filter == 2
                    else (left + above) // 2
                    if row_filter == 3
                    else paeth_prediction(left, above, upper_left)
                )
                row[index] = (encoded + prediction) & 0xFF
            for index in range(0, len(row), 3):
                red, green, blue = row[index : index + 3]
                histogram[
                    ((red >> 4) << 8)
                    | ((green >> 4) << 4)
                    | (blue >> 4)
                ] += 1
                for channel, value in enumerate((red, green, blue)):
                    minimum_channels[channel] = min(
                        minimum_channels[channel],
                        value,
                    )
                    maximum_channels[channel] = max(
                        maximum_channels[channel],
                        value,
                    )
            prior_row = bytes(row)
        overflow = decoder.decompress(compressed_input, 1)
    except zlib.error as exc:
        raise Task11IndependentAuditError(
            f"{label} PNG image data is invalid"
        ) from exc
    _require(
        not buffered
        and not overflow
        and not decoder.unconsumed_tail
        and not decoder.unused_data
        and decoder.eof,
        f"{label} PNG scanlines are invalid",
    )

    pixel_count = width * height
    dominant = max(histogram)
    occupied_bins = sum(count > 0 for count in histogram)
    channel_span = max(
        maximum - minimum
        for minimum, maximum in zip(
            minimum_channels,
            maximum_channels,
            strict=True,
        )
    )
    minimum_non_dominant = max(8, (pixel_count + 199) // 200)
    _require(
        occupied_bins >= 2
        and channel_span >= 16
        and pixel_count - dominant >= minimum_non_dominant,
        f"{label} PNG has insufficient visual content",
    )


def _network_target_is_loopback(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return True
    lowered = normalized.lower()
    if lowered in {"direct", "direct://"} or lowered.startswith(
        ("about:", "blob:", "data:", "file:")
    ):
        return True
    if "://" in normalized:
        parsed = urlsplit(normalized)
        if parsed.scheme.lower() not in {"http", "https", "ws", "wss"}:
            return True
        host = parsed.hostname
    else:
        host = normalized
        if host.startswith("[") and "]" in host:
            host = host[1 : host.index("]")]
        elif host.count(":") == 1:
            host = host.rsplit(":", 1)[0]
        host = host.split("%", 1)[0]
    if host is None:
        return False
    lowered_host = host.lower().rstrip(".")
    if lowered_host == "localhost" or lowered_host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(lowered_host).is_loopback
    except ValueError:
        return False


def _chromium_netlog_evidence(
    path: Path,
    *,
    label: str,
) -> tuple[frozenset[str], tuple[dict[str, object], ...]]:
    payload = _load_object(path, label=f"{label} Chromium netlog")
    events = payload.get("events")
    _require(
        isinstance(events, list)
        and all(isinstance(event, dict) for event in events),
        f"{label} Chromium netlog is invalid",
    )
    target_keys = {
        "address",
        "endpoint",
        "host",
        "hostname",
        "ip_endpoint",
        "original_url",
        "proxy_server",
        "remote_address",
        "url",
    }
    non_loopback_attempts: list[dict[str, object]] = []
    observed_urls: set[str] = set()

    def visit(
        value: object,
        *,
        event_index: int,
        event_type: object,
        key: str | None = None,
    ) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(
                    child,
                    event_index=event_index,
                    event_type=event_type,
                    key=str(child_key),
                )
        elif isinstance(value, list):
            for child in value:
                visit(
                    child,
                    event_index=event_index,
                    event_type=event_type,
                    key=key,
                )
        elif key in target_keys and isinstance(value, str):
            if key in {"url", "original_url"}:
                parsed = urlsplit(value)
                if parsed.scheme in {"http", "https", "ws", "wss"}:
                    observed_urls.add(
                        parsed._replace(fragment="").geturl()
                    )
            if not _network_target_is_loopback(value):
                non_loopback_attempts.append({
                    "event_index": event_index,
                    "event_type": event_type,
                    "field": key,
                    "target": value,
                })

    for event_index, event in enumerate(events):
        params = event.get("params")
        _require(
            params is None or isinstance(params, dict),
            f"{label} Chromium netlog params are invalid",
        )
        if params is not None:
            visit(
                params,
                event_index=event_index,
                event_type=event.get("type"),
            )
    return frozenset(observed_urls), tuple(non_loopback_attempts)


def _validate_chromium_netlog(
    path: Path,
    *,
    label: str,
    required_urls: frozenset[str] = frozenset(),
    allowed_non_loopback_targets: frozenset[str] = frozenset(),
) -> frozenset[str]:
    observed_urls, non_loopback_attempts = _chromium_netlog_evidence(
        path,
        label=label,
    )
    _require(
        all(
            item["target"] in allowed_non_loopback_targets
            for item in non_loopback_attempts
        ),
        f"{label} Chromium netlog contains a non-loopback target",
    )
    _require(
        bool(observed_urls),
        f"{label} Chromium netlog is empty for browser requests",
    )
    _require(
        required_urls <= observed_urls,
        f"{label} Chromium netlog does not bind browser requests",
    )
    return frozenset(observed_urls)


def _validate_browser_requests(
    path: Path,
    *,
    declared_count: int,
    label: str,
) -> frozenset[str]:
    requests = _load_list(path, label=f"{label} browser requests")
    _require(
        len(requests) == declared_count
        and all(isinstance(item, dict) for item in requests),
        f"{label} browser request count is invalid",
    )
    stream_posts = 0
    for item in requests:
        if not isinstance(item, dict):
            raise Task11IndependentAuditError(
                f"{label} browser request evidence is invalid"
            )
        url = item.get("url")
        method = item.get("method")
        resource_type = item.get("resource_type")
        _require(
            isinstance(url, str)
            and isinstance(method, str)
            and _network_target_is_loopback(url),
            f"{label} browser request evidence is invalid",
        )
        _require(
            resource_type in ALLOWED_BROWSER_RESOURCE_TYPES,
            f"{label} browser request resource type is invalid",
        )
        if (
            method.upper() == "POST"
            and urlsplit(url).path == "/api/v1/chat/stream"
        ):
            stream_posts += 1
    _require(
        stream_posts >= len(FIXTURE_TURNS),
        f"{label} browser stream request evidence is incomplete",
    )
    return frozenset(
        urlsplit(item["url"])._replace(fragment="").geturl()
        for item in requests
        if (
            item["resource_type"] != "document"
            or (
                item["method"].upper() == "POST"
                and urlsplit(item["url"]).path
                == "/api/v1/chat/stream"
            )
        )
    )


def _normalize_browser_text(value: object) -> str:
    return " ".join(str(value or "").split())


_CATEGORY_PROFILE_BY_RAW = {
    "乳液": "skincare",
    "乳霜": "skincare",
    "爽肤水": "skincare",
    "眼部精华": "skincare",
    "眼霜": "skincare",
    "精华": "skincare",
    "精华水": "skincare",
    "精华液": "skincare",
    "面膜": "skincare",
    "面霜": "skincare",
    "防晒": "suncare",
    "防晒乳": "suncare",
    "防晒乳液": "suncare",
    "防晒隔离": "suncare",
    "防晒霜": "suncare",
    "妆前乳": "base_makeup",
    "散粉": "base_makeup",
    "气垫": "base_makeup",
    "气垫粉底": "base_makeup",
    "气垫粉底液": "base_makeup",
    "粉底液": "base_makeup",
    "蜜粉": "base_makeup",
    "遮瑕膏": "base_makeup",
    "单色眼影": "color_makeup",
    "口红": "color_makeup",
    "唇膏": "color_makeup",
    "腮红": "color_makeup",
    "卸妆": "cleanser",
    "卸妆水/洁肤液": "cleanser",
    "卸妆洁肤液/卸妆水": "cleanser",
    "洁面/清洁": "cleanser",
    "洁面乳/泡沫洁面乳": "cleanser",
    "洁面乳/洁面泡沫": "cleanser",
    "洁面泡沫": "cleanser",
    "洁面霜/洁面": "cleanser",
    "洁颜油/卸妆油": "cleanser",
    "洁颜霜/卸妆膏": "cleanser",
    "香水": "fragrance",
}


def _load_manifest_bound_jsonl(
    *,
    directory: Path,
    manifest_name: str,
    file_key: str,
    digest_key: str,
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    manifest = _load_object(directory / manifest_name, label=manifest_name)
    filename = manifest.get(file_key)
    expected_digest = manifest.get(digest_key)
    _require(
        isinstance(filename, str)
        and filename
        and isinstance(expected_digest, str)
        and HEX_64.fullmatch(expected_digest) is not None,
        f"{manifest_name} is invalid",
    )
    path = directory / filename
    payload = path.read_bytes()
    _require(
        sha256(payload).hexdigest() == expected_digest,
        f"{manifest_name} payload hash is invalid",
    )
    try:
        rows = tuple(
            json.loads(line)
            for line in payload.decode("utf-8").splitlines()
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Task11IndependentAuditError(
            f"{manifest_name} payload is invalid"
        ) from exc
    _require(
        bool(rows) and all(isinstance(row, dict) for row in rows),
        f"{manifest_name} rows are invalid",
    )
    return manifest, rows


def _asset_link(image_url: object) -> tuple[str | None, str | None]:
    if not isinstance(image_url, str):
        return None, None
    stem = Path(image_url).stem
    parts = stem.split("_")
    if len(parts) < 2 or not parts[-1].isdigit():
        return None, None
    item_id = parts[-1]
    if stem.startswith("tmall_"):
        return "天猫", f"https://detail.tmall.com/item.htm?id={item_id}"
    if stem.startswith("taobao_"):
        return "淘宝", f"https://item.taobao.com/item.htm?id={item_id}"
    if stem.startswith("jd_"):
        return "京东", f"https://item.jd.com/{item_id}.html"
    return None, None


def _known_core_field(
    product: Mapping[str, object],
    key: str,
) -> object | None:
    fields = product.get("fields")
    if not isinstance(fields, dict):
        return None
    field = fields.get(key)
    if (
        not isinstance(field, dict)
        or field.get("resolved_state") != "known"
    ):
        return None
    return field.get("value")


def _canonical_product_sources(root: Path) -> dict[str, object]:
    canonical_root = root / "data" / "canonical"
    _, product_rows = _load_manifest_bound_jsonl(
        directory=canonical_root,
        manifest_name="core_products_v1_manifest.json",
        file_key="products_file",
        digest_key="products_sha256",
    )
    _, asset_rows = _load_manifest_bound_jsonl(
        directory=canonical_root,
        manifest_name="seed_product_images_v1_manifest.json",
        file_key="products_file",
        digest_key="products_sha256",
    )
    _, display_rows = _load_manifest_bound_jsonl(
        directory=root / "data/guide_product_display_bindings/v1",
        manifest_name="product_display_bindings_v1_manifest.json",
        file_key="records_file",
        digest_key="records_sha256",
    )
    _, alias_rows = _load_manifest_bound_jsonl(
        directory=canonical_root,
        manifest_name="controlled_product_aliases_v1_manifest.json",
        file_key="aliases_file",
        digest_key="aliases_sha256",
    )
    _, category_rows = _load_manifest_bound_jsonl(
        directory=root / "data/guide_category_facts",
        manifest_name="category_facts_v1_manifest.json",
        file_key="facts_file",
        digest_key="facts_sha256",
    )
    _, selection_rows = _load_manifest_bound_jsonl(
        directory=root / "data/guide_selection_concepts/v2",
        manifest_name="selection_concepts_v1_manifest.json",
        file_key="projections_file",
        digest_key="projections_sha256",
    )
    _, merchant_rows = _load_manifest_bound_jsonl(
        directory=root / "data/guide_merchant_claims",
        manifest_name="merchant_claims_v1_manifest.json",
        file_key="claims_file",
        digest_key="claims_sha256",
    )
    products = {
        row["product_id"]: row
        for row in product_rows
        if isinstance(row.get("product_id"), int)
    }
    assets = {
        row["product_id"]: row
        for row in asset_rows
        if isinstance(row.get("product_id"), int)
    }
    displays = {
        row["product_id"]: row
        for row in display_rows
        if isinstance(row.get("product_id"), int)
    }
    variants: dict[int, set[str | None]] = {
        product_id: {None} for product_id in products
    }
    for row in alias_rows:
        scope = row.get("variant_scope")
        product_ids = row.get("product_ids")
        if scope is None or not isinstance(product_ids, list):
            continue
        for product_id in product_ids:
            if isinstance(product_id, int) and product_id in variants:
                variants[product_id].add(scope)
    category_facts: dict[int, dict[str, dict[str, object]]] = {}
    for row in category_rows:
        product_id = row.get("product_id")
        key = row.get("field_key")
        if isinstance(product_id, int) and isinstance(key, str):
            category_facts.setdefault(product_id, {})[key] = row
    selection_values: dict[int, dict[str, set[str]]] = {}
    for row in selection_rows:
        product_ids = row.get("product_ids")
        key = row.get("field_key")
        value = row.get("normalized_value")
        if (
            not isinstance(product_ids, list)
            or not isinstance(key, str)
            or not isinstance(value, str)
        ):
            continue
        for product_id in product_ids:
            if isinstance(product_id, int):
                selection_values.setdefault(product_id, {}).setdefault(
                    key,
                    set(),
                ).add(value)
    for row in merchant_rows:
        product_id = row.get("product_id")
        key = row.get("field_key")
        value = row.get("normalized_value")
        capabilities = row.get("capabilities")
        if (
            not isinstance(product_id, int)
            or not isinstance(key, str)
            or not isinstance(value, str)
            or not isinstance(capabilities, list)
            or "display" not in capabilities
        ):
            continue
        selection_values.setdefault(product_id, {}).setdefault(
            key,
            set(),
        ).add(value)
    _require(
        products
        and set(products) == set(assets)
        and all(
            isinstance(row.get("fields"), dict)
            for row in products.values()
        ),
        "canonical product source inventory is invalid",
    )
    return {
        "products": products,
        "assets": assets,
        "displays": displays,
        "variants": {
            product_id: frozenset(scopes)
            for product_id, scopes in variants.items()
        },
        "category_facts": category_facts,
        "selection_values": selection_values,
    }


def _canonical_product_matches(
    card: ProductCard,
    *,
    sources: Mapping[str, object],
) -> bool:
    products = sources.get("products")
    assets = sources.get("assets")
    displays = sources.get("displays")
    variants = sources.get("variants")
    category_facts = sources.get("category_facts")
    selection_values = sources.get("selection_values")
    if not all(
        isinstance(value, dict)
        for value in (
            products,
            assets,
            displays,
            variants,
            category_facts,
            selection_values,
        )
    ):
        return False
    product = products.get(card.product_id)
    asset = assets.get(card.product_id)
    allowed_variants = variants.get(card.product_id)
    if (
        not isinstance(product, dict)
        or not isinstance(asset, dict)
        or not isinstance(allowed_variants, frozenset)
        or card.variant_scope not in allowed_variants
    ):
        return False
    name = _known_core_field(product, "product_identity")
    brand = _known_core_field(product, "brand")
    category = _known_core_field(product, "category")
    price = _known_core_field(product, "price")
    if not isinstance(category, str):
        return False
    profile = _CATEGORY_PROFILE_BY_RAW.get(category)
    display = displays.get(card.product_id)
    if display is not None and not isinstance(display, dict):
        return False
    expected_display_name = (
        display.get("display_name") if display is not None else name
    )
    expected_name = expected_display_name
    alignment = (
        display.get("price_specification_alignment")
        if display is not None
        else "unresolved"
    )
    specification = (
        display.get("display_specification")
        if display is not None and alignment == "aligned"
        else None
    )
    platform, detail_url = _asset_link(asset.get("image_url"))
    if (
        card.category_profile.value != profile
        or card.name != expected_name
        or card.display_name != expected_display_name
        or card.brand != brand
        or card.category != category
        or (
            (card.price is None) != (price is None)
            or (
                price is not None
                and (
                    not isinstance(price, (int, float))
                    or card.price is None
                    or float(card.price) != float(price)
                )
            )
        )
        or card.price_specification_alignment != alignment
        or card.specification != specification
        or card.image_url != asset.get("image_url")
        or card.image_source_sha256 != asset.get("source_image_sha256")
        or card.platform != platform
        or card.detail_url != detail_url
    ):
        return False
    canonical_categories = category_facts.get(card.product_id, {})
    selected_values = selection_values.get(card.product_id, {})
    if (
        not isinstance(canonical_categories, dict)
        or not isinstance(selected_values, dict)
    ):
        return False
    for fact in card.category_facts:
        canonical = canonical_categories.get(fact.field_key)
        if fact.state != "known":
            if fact.value is not None:
                return False
            continue
        expected_value = (
            canonical.get("value")
            if isinstance(canonical, dict)
            else _known_core_field(product, fact.field_key)
        )
        if fact.field_key == "efficacy":
            known_values = {
                value
                for value in (
                    expected_value
                    if isinstance(expected_value, list)
                    else ()
                )
                if isinstance(value, str)
            }
            core_efficacy = _known_core_field(product, "efficacy")
            if isinstance(core_efficacy, list):
                known_values.update(
                    value
                    for value in core_efficacy
                    if isinstance(value, str)
                )
            known_values.update(
                value
                for value in selected_values.get("efficacy", set())
                if isinstance(value, str)
            )
            if (
                not isinstance(fact.value, tuple)
                or not set(fact.value) <= known_values
            ):
                return False
            continue
        expected_values = {
            value
            for value in (
                expected_value
                if isinstance(expected_value, list)
                else (
                    [expected_value]
                    if isinstance(expected_value, str)
                    else []
                )
            )
            if isinstance(value, str)
        }
        expected_values.update(
            value
            for value in selected_values.get(fact.field_key, set())
            if isinstance(value, str)
        )
        if (
            (
                isinstance(canonical, dict)
                and canonical.get("category_profile") != profile
            )
            or not expected_values
            or not isinstance(fact.value, tuple)
            or not set(fact.value) <= expected_values
        ):
            return False
    efficacy = _known_core_field(product, "efficacy")
    known_efficacies = {
        value
        for value in (
            efficacy if isinstance(efficacy, list) else ()
        )
        if isinstance(value, str)
    }
    category_efficacy = canonical_categories.get("efficacy")
    if isinstance(category_efficacy, dict):
        value = category_efficacy.get("value")
        if isinstance(value, list):
            known_efficacies.update(
                item for item in value if isinstance(item, str)
            )
    known_efficacies.update(
        value
        for value in selected_values.get("efficacy", set())
        if isinstance(value, str)
    )
    return (
        set(card.matched_efficacies) <= known_efficacies
        and card.skin_match in {"matched", "unknown", "not_applicable"}
    )


def _validate_browser_products(
    *,
    events: Sequence[tuple[str, Mapping[str, object]]],
    visible_ids: Sequence[object],
    sources: Mapping[str, object] | None,
    label: str,
) -> None:
    payloads = [data for event, data in events if event == "products"]
    if not visible_ids:
        _require(
            not payloads,
            f"{label} contains products without visible product IDs",
        )
        return
    _require(
        len(payloads) == 1,
        f"{label} must contain one products event",
    )
    raw_cards = payloads[0].get("cards")
    raw_products = payloads[0].get("products")
    _require(
        isinstance(raw_cards, list)
        and isinstance(raw_products, list)
        and all(isinstance(item, dict) for item in raw_cards)
        and all(isinstance(item, dict) for item in raw_products),
        f"{label} products payload is invalid",
    )
    try:
        cards = tuple(
            ProductCard.model_validate_json(
                json.dumps(item, ensure_ascii=False)
            )
            for item in raw_cards
        )
    except (TypeError, ValueError) as exc:
        raise Task11IndependentAuditError(
            f"{label} typed product card is invalid"
        ) from exc
    expected_ids = tuple(visible_ids)
    _require(
        tuple(card.product_id for card in cards) == expected_ids
        and tuple(item.get("product_id") for item in raw_products)
        == expected_ids,
        f"{label} product IDs do not match the contract",
    )
    _require(
        all(
            _canonical_product_matches(
                card,
                sources=sources,
            )
            for card in cards
        ),
        f"{label} canonical product binding is invalid",
    )
    _require(
        tuple(project_frontend_product(card) for card in cards)
        == tuple(raw_products),
        f"{label} frontend product projection is invalid",
    )


def _validate_browser_dom(
    *,
    request: Mapping[str, object],
    contract: Mapping[str, object],
    dom: Mapping[str, object],
    label: str,
) -> None:
    sections = contract.get("sections", [])
    visible_ids = contract.get("visible_product_ids", [])
    _require(
        isinstance(sections, list)
        and isinstance(visible_ids, list),
        f"{label} contract projection is invalid",
    )
    section_kinds = [
        section.get("kind")
        for section in sections
        if isinstance(section, dict)
    ]
    inline_ids = [
        section.get("product_id")
        for section in sections
        if isinstance(section, dict)
        and section.get("kind") == "product"
        and isinstance(section.get("product_id"), int)
    ]
    _require(
        dom.get("request_id") == request.get("request_id"),
        f"{label} DOM request ID mismatch",
    )
    _require(
        dom.get("terminal_kind") == "presentation"
        and dom.get("presentation_mode") == contract.get("mode"),
        f"{label} DOM presentation mode mismatch",
    )
    _require(
        dom.get("visible_section_kinds") == section_kinds,
        f"{label} DOM section order mismatch",
    )
    blocks = dom.get("section_blocks")
    _require(
        isinstance(blocks, list) and len(blocks) == len(sections),
        f"{label} DOM section blocks mismatch",
    )
    for section, block in zip(sections, blocks, strict=True):
        _require(
            isinstance(section, dict)
            and isinstance(block, dict)
            and block.get("kind") == section.get("kind"),
            f"{label} DOM section block order mismatch",
        )
        block_text = _normalize_browser_text(block.get("text"))
        required_text = [
            section.get("copy_text"),
            section.get("advisor_reason"),
            *[
                fact.get("display_value")
                for fact in section.get("direct_facts", [])
                if isinstance(fact, dict)
            ],
        ]
        _require(
            all(
                _normalize_browser_text(text) in block_text
                for text in required_text
                if isinstance(text, str) and text.strip()
            ),
            f"{label} DOM section text mismatch",
        )
    _require(
        dom.get("inline_product_ids") == inline_ids,
        f"{label} DOM inline product IDs mismatch",
    )
    _require(
        dom.get("visible_product_ids") == visible_ids
        and dom.get("shelf_product_ids") == visible_ids,
        f"{label} DOM visible product IDs mismatch",
    )
    _require(
        dom.get("legacy_message_count") == 0
        and dom.get("legacy_product_card_count") == 0
        and dom.get("turn_presentation_root_count") == 1,
        f"{label} DOM legacy or root ownership mismatch",
    )
    expected_tables = 1 if contract.get("mode") == "comparison" else 0
    _require(
        dom.get("comparison_table_count") == expected_tables,
        f"{label} DOM comparison table mismatch",
    )


def _validate_fixture_turn_contract(
    *,
    turn_id: str,
    request: Mapping[str, object],
    contract: Mapping[str, object],
    label: str,
) -> None:
    expected = FIXTURE_PRESENTATION_EXPECTATIONS.get(turn_id)
    _require(
        expected is not None,
        f"{label} fixture expectation is missing",
    )
    (
        responsibility,
        mode,
        recommendation_mode,
        product_count,
        requires_image,
    ) = expected
    visible_ids = contract.get("visible_product_ids")
    _require(
        contract.get("responsibility") == responsibility
        and contract.get("mode") == mode
        and "recommendation_mode" in contract
        and contract.get("recommendation_mode") == recommendation_mode
        and isinstance(visible_ids, list)
        and len(visible_ids) == product_count
        and all(
            type(product_id) is int and product_id > 0
            for product_id in visible_ids
        ),
        f"{label} fixture {turn_id} presentation contract is invalid",
    )
    card_display = contract.get("card_display")
    _require(
        isinstance(card_display, dict)
        and card_display.get("visible_product_ids") == visible_ids,
        f"{label} fixture {turn_id} card display is invalid",
    )
    if recommendation_mode == "fit":
        winner = contract.get("winner")
        _require(
            isinstance(winner, dict)
            and winner.get("status") == "selected"
            and winner.get("winner_product_id") == visible_ids[0],
            f"{label} fixture {turn_id} fit winner is invalid",
        )
    if requires_image:
        body = request.get("body")
        _require(
            isinstance(body, dict)
            and isinstance(body.get("image_bundle_id"), str)
            and bool(body["image_bundle_id"])
            and type(body.get("image_bundle_version")) is int
            and body["image_bundle_version"] > 0
            and isinstance(body.get("image_bundle_token"), str)
            and bool(body["image_bundle_token"]),
            f"{label} fixture {turn_id} image request is invalid",
        )


def _validate_browser_summary(
    *,
    repo_root: Path,
    path: Path,
    payload: Mapping[str, object],
    viewport: str,
) -> tuple[str, str]:
    label = f"{viewport} browser summary"
    _require(
        payload.get("schema_version")
        == "guide-mainline-contract-browser-audit-v1",
        f"{label} schema is invalid",
    )
    _require(
        payload.get("evidence_scope") == "frontend_fixture_only"
        and payload.get("backend_path_claim") is False,
        f"{label} fixture evidence scope is invalid",
    )
    _require(
        payload.get("trajectory_set") == "fixture"
        and payload.get("viewport") == viewport
        and payload.get("passed") is True,
        f"{label} identity or verdict is invalid",
    )
    _require(
        _required_int(payload, "turn_count", label=label)
        == len(FIXTURE_TURNS),
        f"{label} turn count is invalid",
    )
    _required_zero(payload, "invalid_clarification_count", label=label)
    runtime_digest = payload.get("runtime_identity_sha256")
    challenge_digest = payload.get(
        "consumed_health_challenge_sha256",
        payload.get(
            "consumed_challenge_sha256",
            payload.get("health_challenge_sha256"),
        ),
    )
    sandbox_digest = payload.get("sandbox_audit_sha256")
    _require(
        _is_digest(runtime_digest)
        and _is_digest(challenge_digest)
        and _is_digest(sandbox_digest),
        f"{label} runtime, challenge, or sandbox digest is invalid",
    )
    _require(
        isinstance(payload.get("sandbox_identity"), str)
        and bool(payload["sandbox_identity"]),
        f"{label} sandbox identity is missing",
    )
    _require(
        _required_int(payload, "browser_request_count", label=label)
        >= len(FIXTURE_TURNS),
        f"{label} browser request count is invalid",
    )
    _required_zero(
        payload,
        "process_tree_non_loopback_attempt_count",
        label=label,
    )
    _required_zero(
        payload,
        "browser_observed_non_loopback_attempt_count",
        label=label,
    )

    turns = payload.get("turns")
    _require(
        isinstance(turns, list) and len(turns) == len(FIXTURE_TURNS),
        f"{label} turn inventory is invalid",
    )
    turn_ids: list[str] = []
    for item in turns:
        _require(isinstance(item, dict), f"{label} turn item is invalid")
        turn_id = item.get("turn_id")
        directory = item.get("directory", turn_id)
        _require(
            isinstance(turn_id, str)
            and isinstance(directory, str)
            and directory == turn_id,
            f"{label} turn directory is invalid",
        )
        turn_ids.append(turn_id)
    _require(
        tuple(turn_ids) == FIXTURE_TURNS,
        f"{label} fixture turn inventory is incomplete",
    )

    root = path.parent
    sandbox_bytes = _validate_seatbelt_audit(
        root=root,
        summary=payload,
        label=label,
    )
    browser_request_urls = _validate_browser_requests(
        root / "browser-requests.json",
        declared_count=_required_int(
            payload,
            "browser_request_count",
            label=label,
        ),
        label=label,
    )
    _validate_chromium_netlog(
        root / "chromium-netlog.json",
        label=label,
        required_urls=browser_request_urls,
        allowed_non_loopback_targets=frozenset({
            CHROMIUM_IPV6_PROBE_TARGET
        }),
    )
    expected_index: dict[str, str] = {}
    for artifact in sorted(root.rglob("*")):
        if artifact == path:
            continue
        _require(
            not artifact.is_symlink(),
            f"{label} contains a symlinked artifact",
        )
        if artifact.is_file():
            expected_index[artifact.relative_to(root).as_posix()] = (
                _digest_file(artifact)
            )
    declared_index = _artifact_index(payload)
    _require(
        declared_index == expected_index,
        f"{label} artifact hash index is stale or incomplete",
    )
    _require(
        sandbox_digest == sha256(sandbox_bytes).hexdigest(),
        f"{label} sandbox audit hash is not bound to an artifact",
    )

    canonical_sources = None
    for turn_id in FIXTURE_TURNS:
        turn_dir = root / turn_id
        _require(turn_dir.is_dir(), f"{label} turn directory is missing")
        names = {
            item.name for item in turn_dir.iterdir() if item.is_file()
        }
        _require(
            REQUIRED_BROWSER_FILES <= names,
            f"{label} turn {turn_id} is missing evidence files",
        )
        request = _load_object(
            turn_dir / "request.json",
            label=f"{label} request",
        )
        _require(
            request.get("turn_id") == turn_id
            and isinstance(request.get("request_id"), str)
            and bool(request["request_id"]),
            f"{label} request identity is invalid",
        )
        contract = _load_object(
            turn_dir / "presentation-contract.json",
            label=f"{label} presentation contract",
        )
        dom = _load_object(
            turn_dir / "terminal-dom.json",
            label=f"{label} terminal DOM",
        )
        events = _sse_events(
            (turn_dir / "stream.sse").read_text(encoding="utf-8"),
            label=f"{label} stream",
        )
        event_names = [event for event, _ in events]
        is_clarification = turn_id == "fixture-fit-clarification"
        _require(
            event_names
            and event_names[0] == "start"
            and event_names[-1] == "end"
            and event_names.count("start") == 1
            and event_names.count("end") == 1
            and event_names.count("presentation_contract")
            == (0 if is_clarification else 1)
            and event_names.count("clarify")
            == (1 if is_clarification else 0)
            and not {"error", "message"} & set(event_names),
            f"{label} stream lifecycle is invalid",
        )
        start_payload = events[0][1]
        end_payload = events[-1][1]
        _require(
            isinstance(start_payload.get("session_id"), str)
            and bool(start_payload["session_id"])
            and type(end_payload.get("conversation_version")) is int
            and int(end_payload["conversation_version"]) >= 1,
            f"{label} stream boundary payload is invalid",
        )
        contracts = [
            data for event, data in events if event == "presentation_contract"
        ]
        if is_clarification:
            clarification_events = [
                data for event, data in events if event == "clarify"
            ]
            clarification = contract.get("clarification")
            _require(
                contract.get("terminal_kind") == "clarification"
                and isinstance(clarification, dict)
                and clarification_events == [clarification]
                and isinstance(clarification.get("question"), str)
                and bool(clarification["question"])
                and clarification.get("clarification_code") == "goal"
                and clarification.get("intended_responsibility")
                == "recommendation"
                and clarification.get("intended_recommendation_mode")
                == "fit"
                and clarification.get("clarification_basis")
                == "fit_selection_evidence_gap"
                and clarification.get("fit_gap_stage")
                == "decision_selection"
                and clarification.get("fit_decision_status")
                == "INSUFFICIENT_FOR_WINNER"
                and type(clarification.get("fit_candidate_count")) is int
                and type(
                    clarification.get("fit_evidence_ref_count")
                ) is int
                and clarification.get("fit_public_fact_count") == 0,
                f"{label} clarification terminal is invalid",
            )
            _require(
                dom.get("terminal_kind") == "clarification"
                and dom.get("presentation_mode") is None
                and dom.get("legacy_message_count") == 0
                and dom.get("clarification_message_count") == 1
                and dom.get("legacy_product_card_count") == 0
                and dom.get("turn_presentation_root_count") == 0
                and dom.get("visible_section_kinds") == []
                and dom.get("inline_product_ids") == []
                and dom.get("visible_product_ids") == []
                and dom.get("shelf_product_ids") == []
                and clarification["question"]
                in str(dom.get("presentation_text", "")),
                f"{label} clarification DOM shape is invalid",
            )
            visible_ids: object = []
        else:
            _require(
                contracts == [contract],
                f"{label} emitted presentation bytes do not match the contract",
            )
            _validate_fixture_turn_contract(
                turn_id=turn_id,
                request=request,
                contract=contract,
                label=label,
            )
            _validate_browser_dom(
                request=request,
                contract=contract,
                dom=dom,
                label=f"{label} turn {turn_id}",
            )
            visible_ids = contract.get("visible_product_ids", [])
        _require(
            any(event == "end" for event, _ in events),
            f"{label} stream has no terminal end event",
        )
        if visible_ids and canonical_sources is None:
            canonical_sources = _canonical_product_sources(repo_root)
        if canonical_sources is None:
            _validate_browser_products(
                events=events,
                visible_ids=visible_ids if isinstance(visible_ids, list) else [],
                sources=None,
                label=f"{label} turn {turn_id}",
            )
        else:
            _validate_browser_products(
                events=events,
                visible_ids=visible_ids if isinstance(visible_ids, list) else [],
                sources=canonical_sources,
                label=f"{label} turn {turn_id}",
            )
        _validate_png(
            turn_dir / "screenshot.png",
            viewport=viewport,
            label=f"{label} turn {turn_id}",
        )
        _require(
            _load_list(
                turn_dir / "console.json",
                label=f"{label} console",
            )
            == [],
            f"{label} browser console is not empty",
        )
        _require(
            _load_list(
                turn_dir / "network.json",
                label=f"{label} browser network",
            )
            == [],
            f"{label} browser network failures are not empty",
        )
        sandbox = _load_object(
            turn_dir / "sandbox-audit.json",
            label=f"{label} sandbox audit",
        )
        _require(
            (turn_dir / "sandbox-audit.json").read_bytes()
            == sandbox_bytes
            and sandbox.get("passed") is True
            and sandbox.get("attempts") == []
            and sandbox.get("process_tree_non_loopback_attempt_count") == 0,
            f"{label} turn sandbox evidence failed",
        )
    return str(runtime_digest), str(challenge_digest)


def _repair_epoch(path: Path) -> int:
    match = re.fullmatch(r"repair-epoch-(\d+)", path.parent.name)
    _require(match is not None, "audit output is not epoch-owned")
    return int(match.group(1))


def _candidate_manifest_path_is_valid(
    *,
    root: Path,
    path: Path,
    repair_epoch: int,
    plan_revision: object,
) -> bool:
    epoch_root = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / f"repair-epoch-{repair_epoch}"
    ).resolve()
    canonical = epoch_root / "task11-candidate-manifest.json"
    if path.resolve() == canonical:
        return True
    revision_match = re.search(r"-(r\d+)$", str(plan_revision))
    if revision_match is None:
        return False
    expected = epoch_root / (
        f"task11-candidate-manifest-{revision_match.group(1)}.json"
    )
    return path.resolve() == expected


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _decode_runtime_provenance_value(
    value: object,
    *,
    length: int,
) -> bytes:
    _require(
        isinstance(value, str) and bool(value),
        "runtime provenance signature is invalid",
    )
    try:
        decoded = base64.b64decode(
            value + ("=" * (-len(value) % 4)),
            altchars=b"-_",
            validate=True,
        )
    except (TypeError, ValueError) as exc:
        raise Task11IndependentAuditError(
            "runtime provenance signature is invalid"
        ) from exc
    canonical = (
        base64.urlsafe_b64encode(decoded)
        .decode("ascii")
        .rstrip("=")
    )
    _require(
        len(decoded) == length and canonical == value,
        "runtime provenance signature is invalid",
    )
    return decoded


def _verify_runtime_provenance_signature(
    *,
    public_key: object,
    signature: object,
    domain: bytes,
    payload: Mapping[str, object],
) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(
            _decode_runtime_provenance_value(
                public_key,
                length=32,
            )
        ).verify(
            _decode_runtime_provenance_value(
                signature,
                length=64,
            ),
            domain + _canonical_json_bytes(dict(payload)),
        )
    except (InvalidSignature, ValueError) as exc:
        raise Task11IndependentAuditError(
            "runtime provenance signature is invalid"
        ) from exc


def _validate_runtime_provenance(
    *,
    manifest_path: Path,
    manifest: Mapping[str, object],
    runtime_report: Mapping[str, object],
    browser_summaries: tuple[
        tuple[Path, Mapping[str, object]],
        ...,
    ],
) -> None:
    signed_runtime_report = dict(runtime_report)
    runtime_report_signature = signed_runtime_report.pop(
        "runtime_report_signature",
        None,
    )
    runtime_public_key = signed_runtime_report.get(
        "fixture_runtime_public_key"
    )
    runtime_public_keys = manifest.get("fixture_runtime_public_keys")
    _require(
        isinstance(runtime_public_keys, list)
        and runtime_public_key in runtime_public_keys,
        "runtime provenance report authority is invalid",
    )
    _verify_runtime_provenance_signature(
        public_key=runtime_public_key,
        signature=runtime_report_signature,
        domain=RUNTIME_REPORT_SIGNATURE_DOMAIN,
        payload=signed_runtime_report,
    )
    runtime_digest = runtime_report.get("runtime_identity_sha256")
    consumed_digests = runtime_report.get(
        "consumed_health_challenge_sha256s"
    )
    _require(
        _is_digest(runtime_digest)
        and isinstance(consumed_digests, list)
        and len(consumed_digests) == len(browser_summaries)
        and len(consumed_digests) == len(set(consumed_digests))
        and all(_is_digest(value) for value in consumed_digests),
        "runtime provenance is invalid",
    )
    observed_identity_bytes: list[bytes] = []
    observed_challenge_digests: list[str] = []
    for summary_path, summary in browser_summaries:
        identity_path = (
            summary_path.parent / RUNTIME_IDENTITY_ARTIFACT
        )
        challenge_path = (
            summary_path.parent / CONSUMED_CHALLENGE_ARTIFACT
        )
        _require(
            identity_path.is_file()
            and not identity_path.is_symlink()
            and challenge_path.is_file()
            and not challenge_path.is_symlink(),
            "runtime provenance originals are missing",
        )
        identity_bytes = identity_path.read_bytes()
        identity = _load_object(
            identity_path,
            label="runtime provenance identity",
        )
        challenge_bytes = challenge_path.read_bytes()
        challenge = _load_object(
            challenge_path,
            label="runtime provenance challenge",
        )
        _require(
            identity_bytes == _canonical_json_bytes(identity)
            and challenge_bytes == _canonical_json_bytes(challenge),
            "runtime provenance originals are not canonical",
        )
        base_url = str(summary.get("base_url", ""))
        parsed = urlsplit(base_url)
        try:
            summary_port = parsed.port
        except ValueError as exc:
            raise Task11IndependentAuditError(
                "runtime provenance identity is invalid"
            ) from exc
        process_identity = identity.get("process_identity")
        signed_identity = dict(identity)
        identity_signature = signed_identity.pop(
            "identity_signature",
            None,
        )
        unsigned_identity = dict(signed_identity)
        identity_self_digest = unsigned_identity.pop(
            "identity_sha256",
            None,
        )
        _verify_runtime_provenance_signature(
            public_key=runtime_public_key,
            signature=identity_signature,
            domain=RUNTIME_IDENTITY_SIGNATURE_DOMAIN,
            payload=signed_identity,
        )
        identity_file_digest = sha256(identity_bytes).hexdigest()
        _require(
            set(identity)
            == {
                "schema_version",
                "candidate_manifest_path",
                "candidate_manifest_sha256",
                "plan_revision",
                "code_revision",
                "protected_payload_sha256",
                "process_identity",
                "host",
                "port",
                "state_dir",
                "runtime_nonce",
                "runtime_public_key",
                "identity_sha256",
                "identity_signature",
            }
            and identity.get("schema_version")
            == RUNTIME_IDENTITY_SCHEMA
            and identity.get("candidate_manifest_path")
            == str(manifest_path.resolve())
            and identity.get("candidate_manifest_sha256")
            == _digest_file(manifest_path)
            and identity.get("plan_revision")
            == manifest.get("plan_revision")
            and identity.get("code_revision")
            == manifest.get("candidate_head")
            and identity.get("protected_payload_sha256")
            == manifest.get("protected_payload_sha256")
            and identity.get("runtime_public_key")
            == runtime_public_key
            and isinstance(process_identity, dict)
            and set(process_identity) == {"pid"}
            and type(process_identity.get("pid")) is int
            and int(process_identity["pid"]) > 0
            and parsed.scheme == "http"
            and parsed.hostname is not None
            and _network_target_is_loopback(base_url)
            and summary_port is not None
            and identity.get("host") == parsed.hostname
            and identity.get("port") == summary_port
            and isinstance(identity.get("state_dir"), str)
            and bool(identity["state_dir"])
            and isinstance(identity.get("runtime_nonce"), str)
            and HEX_64.fullmatch(identity["runtime_nonce"]) is not None
            and identity["runtime_nonce"] != "0" * 64
            and isinstance(identity_self_digest, str)
            and identity_self_digest
            == sha256(
                _canonical_json_bytes(unsigned_identity)
            ).hexdigest()
            and identity_file_digest == runtime_digest
            and summary.get("runtime_identity_sha256")
            == identity_file_digest
            and runtime_report.get("runtime_root_pid")
            == process_identity["pid"]
            and runtime_report.get("root_pid")
            == process_identity["pid"],
            "runtime provenance identity is invalid",
        )

        unsigned_challenge = {
            "schema_version": challenge.get("schema_version"),
            "runtime_identity_sha256": challenge.get(
                "runtime_identity_sha256"
            ),
            "challenge": challenge.get("challenge"),
        }
        challenge_digest = challenge.get("challenge_sha256")
        signed_challenge = dict(challenge)
        challenge_signature = signed_challenge.pop(
            "challenge_signature",
            None,
        )
        _verify_runtime_provenance_signature(
            public_key=runtime_public_key,
            signature=challenge_signature,
            domain=RUNTIME_CHALLENGE_SIGNATURE_DOMAIN,
            payload=signed_challenge,
        )
        _require(
            set(challenge)
            == {
                "schema_version",
                "runtime_identity_sha256",
                "challenge",
                "challenge_sha256",
                "challenge_signature",
            }
            and unsigned_challenge["schema_version"]
            == RUNTIME_CHALLENGE_SCHEMA
            and unsigned_challenge["runtime_identity_sha256"]
            == identity_file_digest
            and isinstance(unsigned_challenge["challenge"], str)
            and HEX_64.fullmatch(unsigned_challenge["challenge"])
            is not None
            and unsigned_challenge["challenge"] != "0" * 64
            and isinstance(challenge_digest, str)
            and challenge_digest
            == sha256(
                _canonical_json_bytes(unsigned_challenge)
            ).hexdigest()
            and summary.get("consumed_health_challenge_sha256")
            == challenge_digest,
            "runtime provenance challenge is invalid",
        )
        observed_identity_bytes.append(identity_bytes)
        observed_challenge_digests.append(str(challenge_digest))

    _require(
        len(set(observed_identity_bytes)) == 1
        and observed_challenge_digests == consumed_digests,
        "runtime provenance binding is invalid",
    )


def _failure_evidence_digest(directory: Path) -> tuple[
    dict[str, str],
    str,
]:
    required = (
        "console.json",
        "network.json",
        "presentation-contract.json",
        "request.json",
        "screenshot.png",
        "stream.sse",
        "terminal-dom.json",
    )
    hashes: dict[str, str] = {}
    digest = sha256()
    for name in required:
        path = _input_file(
            directory / name,
            label=f"failure evidence {name}",
        )
        content = path.read_bytes()
        name_bytes = name.encode("utf-8")
        hashes[name] = sha256(content).hexdigest()
        digest.update(str(len(name_bytes)).encode("ascii"))
        digest.update(b":")
        digest.update(name_bytes)
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b":")
        digest.update(content)
    return hashes, digest.hexdigest()


def _recorded_failure_evidence_digest(
    attempt: Mapping[str, object],
    *,
    directory: Path,
) -> tuple[dict[str, str], str]:
    manifest = attempt.get("terminal_evidence")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version")
        != "guide-attempt-terminal-evidence-v1"
        or Path(str(manifest.get("root"))).resolve()
        != directory.resolve()
        or not isinstance(manifest.get("sha256_by_path"), dict)
    ):
        raise Task11IndependentAuditError(
            "recorded failure evidence is invalid"
        )
    hashes = {
        str(relative): str(expected_sha256)
        for relative, expected_sha256
        in manifest["sha256_by_path"].items()
    }
    context_path = Path(str(attempt.get("context_path"))).resolve()
    output_root = context_path.parent
    digest = sha256()
    for relative, expected_sha256 in sorted(hashes.items()):
        relative_path = Path(relative)
        _require(
            not relative_path.is_absolute()
            and relative_path.as_posix() == relative
            and all(
                part not in {"", ".", ".."}
                for part in relative_path.parts
            )
            and _is_digest(expected_sha256),
            "recorded failure evidence is invalid",
        )
        path = _input_file(
            output_root / relative_path,
            label=f"recorded failure evidence {relative}",
        )
        _require(
            directory == path.parent or directory in path.parents,
            "recorded failure evidence escapes its terminal root",
        )
        content = path.read_bytes()
        _require(
            sha256(content).hexdigest() == expected_sha256,
            "recorded failure evidence hash mismatch",
        )
        name_bytes = relative.encode("utf-8")
        digest.update(str(len(name_bytes)).encode("ascii"))
        digest.update(b":")
        digest.update(name_bytes)
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b":")
        digest.update(content)
    _require(bool(hashes), "recorded failure evidence is empty")
    return hashes, digest.hexdigest()


def _junit_inventory(
    path: Path,
    *,
    label: str,
) -> dict[str, object]:
    source = _input_file(path, label=label)
    try:
        root = ElementTree.parse(source).getroot()
    except (ElementTree.ParseError, OSError) as error:
        raise Task11IndependentAuditError(
            "repair JUnit evidence is invalid"
        ) from error
    suites = (
        [root]
        if root.tag.rsplit("}", 1)[-1] == "testsuite"
        else [
            item
            for item in root.iter()
            if item.tag.rsplit("}", 1)[-1] == "testsuite"
        ]
    )
    _require(bool(suites), "repair JUnit evidence has no test suite")
    testcases = [
        item
        for item in root.iter()
        if item.tag.rsplit("}", 1)[-1] == "testcase"
    ]
    _require(bool(testcases), "repair JUnit evidence has no test cases")
    try:
        declared_tests = sum(
            int(item.attrib.get("tests", "0")) for item in suites
        )
        declared_failures = sum(
            int(item.attrib.get("failures", "0")) for item in suites
        )
        declared_errors = sum(
            int(item.attrib.get("errors", "0")) for item in suites
        )
        declared_skipped = sum(
            int(item.attrib.get("skipped", "0")) for item in suites
        )
    except ValueError as error:
        raise Task11IndependentAuditError(
            "repair JUnit counters are invalid"
        ) from error
    statuses: dict[str, str] = {}
    failure_text: dict[str, str] = {}
    for testcase in testcases:
        classname = testcase.attrib.get("classname")
        name = testcase.attrib.get("name")
        _require(
            isinstance(classname, str)
            and bool(classname)
            and isinstance(name, str)
            and bool(name),
            "repair JUnit testcase identity is invalid",
        )
        node_id = (
            classname.replace(".", "/")
            + ".py::"
            + name
        )
        _require(
            node_id not in statuses,
            "repair JUnit testcase identity is duplicated",
        )
        outcomes = [
            child
            for child in testcase
            if child.tag.rsplit("}", 1)[-1]
            in {"failure", "error", "skipped"}
        ]
        _require(
            len(outcomes) <= 1,
            "repair JUnit testcase outcome is ambiguous",
        )
        status = (
            outcomes[0].tag.rsplit("}", 1)[-1]
            if outcomes
            else "passed"
        )
        statuses[node_id] = status
        if status in {"failure", "error"}:
            failure_text[node_id] = (
                str(outcomes[0].attrib.get("message", ""))
                + "\n"
                + str(outcomes[0].text or "")
            )
    actual_failures = sum(
        status == "failure" for status in statuses.values()
    )
    actual_errors = sum(
        status == "error" for status in statuses.values()
    )
    actual_skipped = sum(
        status == "skipped" for status in statuses.values()
    )
    _require(
        declared_tests == len(statuses)
        and declared_failures == actual_failures
        and declared_errors == actual_errors
        and declared_skipped == actual_skipped,
        "repair JUnit counters do not match testcase inventory",
    )
    return {
        "tests": len(statuses),
        "failures": actual_failures,
        "errors": actual_errors,
        "skipped": actual_skipped,
        "statuses": statuses,
        "failure_text": failure_text,
    }


def _git_blob_sha1(path: Path) -> str:
    content = path.read_bytes()
    return sha1(
        b"blob "
        + str(len(content)).encode("ascii")
        + b"\0"
        + content
    ).hexdigest()


def _reverse_apply_historical_patch_descendant(
    *,
    root: Path,
    patch_path: Path,
    label: str,
) -> None:
    sections = [
        section
        for section in re.split(
            r"(?=^diff --git )",
            patch_path.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
        if section
    ]
    _require(bool(sections), f"{label} has no file sections")
    for section in sections:
        header = re.match(
            r"diff --git a/(.+?) b/(.+?)\n",
            section,
        )
        _require(
            header is not None and header.group(1) == header.group(2),
            f"{label} path identity is invalid",
        )
        relative = str(header.group(1))
        target = _input_file(
            root / relative,
            label=f"{label} target {relative}",
        )
        target_lines = target.read_text(encoding="utf-8").splitlines(
            keepends=True
        )
        changed_runs: list[
            tuple[list[str], list[str], list[str], list[str]]
        ] = []
        hunks = [
            hunk
            for hunk in re.split(
                r"(?=^@@ )",
                section,
                flags=re.MULTILINE,
            )
            if hunk.startswith("@@ ")
        ]
        for hunk in hunks:
            entries = [
                (line[0], line[1:])
                for line in hunk.splitlines(keepends=True)[1:]
                if line
                and line[0] in {" ", "+", "-"}
                and not line.startswith("\\ No newline")
            ]
            index = 0
            while index < len(entries):
                if entries[index][0] == " ":
                    index += 1
                    continue
                run_start = index
                old_lines: list[str] = []
                new_lines: list[str] = []
                while index < len(entries) and entries[index][0] != " ":
                    marker, content = entries[index]
                    if marker == "-":
                        old_lines.append(content)
                    elif marker == "+":
                        new_lines.append(content)
                    index += 1
                before_context = [
                    content
                    for marker, content in entries[:run_start]
                    if marker == " "
                ][-3:]
                after_context = [
                    content
                    for marker, content in entries[index:]
                    if marker == " "
                ][:3]
                changed_runs.append(
                    (
                        old_lines,
                        new_lines,
                        before_context,
                        after_context,
                    )
                )
        _require(
            bool(changed_runs),
            f"{label} has no reversible content",
        )
        for (
            old_run,
            new_run,
            before_context,
            after_context,
        ) in changed_runs:
            replacement_end: int | None = None
            if new_run:
                matches = [
                    index
                    for index in range(
                        len(target_lines) - len(new_run) + 1
                    )
                    if target_lines[index:index + len(new_run)] == new_run
                ]
            else:
                matches = [
                    index
                    for index in range(len(target_lines) + 1)
                    if after_context
                    and target_lines[
                        index:index + len(after_context)
                    ] == after_context
                    and (
                        not before_context
                        or _is_ordered_subsequence(
                            before_context,
                            target_lines[max(0, index - 64):index],
                        )
                    )
                ]
                replacement_end = matches[0] if len(matches) == 1 else None
            if not matches and before_context and after_context:
                def ordered_spans(
                    expected: Sequence[str],
                ) -> list[tuple[int, int]]:
                    spans: list[tuple[int, int]] = []
                    for first in range(len(target_lines)):
                        if target_lines[first] != expected[0]:
                            continue
                        cursor = first + 1
                        for expected_line in expected[1:]:
                            while (
                                cursor < len(target_lines)
                                and target_lines[cursor]
                                != expected_line
                            ):
                                cursor += 1
                            if cursor >= len(target_lines):
                                break
                            cursor += 1
                        else:
                            if cursor - first <= len(expected) + 32:
                                spans.append((first, cursor))
                    return spans

                before_matches = ordered_spans(before_context)
                after_matches = ordered_spans(after_context)
                descendant_spans: list[tuple[int, int]] = []
                for _, start in before_matches:
                    for end, _ in after_matches:
                        if (
                            start <= end
                            and end - start <= len(new_run) + 32
                        ):
                            candidate = target_lines[start:end]
                            matching_lines = sum(
                                block.size
                                for block in SequenceMatcher(
                                    a=new_run,
                                    b=candidate,
                                    autojunk=False,
                                ).get_matching_blocks()
                            )
                            if (
                                matching_lines
                                >= max(2, (len(new_run) + 1) // 2)
                                and candidate
                                and (
                                    candidate[0] == new_run[0]
                                    or candidate[-1] == new_run[-1]
                                )
                            ):
                                descendant_spans.append((start, end))
                if len(descendant_spans) == 1:
                    matches = [descendant_spans[0][0]]
                    replacement_end = descendant_spans[0][1]
            _require(
                len(matches) == 1,
                f"{label} does not reverse-apply to the candidate",
            )
            index = matches[0]
            before_window = target_lines[max(0, index - 64):index]
            after_start = (
                replacement_end
                if replacement_end is not None
                else index + len(new_run)
            )
            after_window = target_lines[after_start:after_start + 64]
            context_matches = (
                _is_ordered_subsequence(
                    before_context,
                    before_window,
                )
                if before_context
                else _is_ordered_subsequence(
                    after_context,
                    after_window,
                )
            )
            _require(
                (
                    before_context or after_context
                )
                and context_matches,
                f"{label} does not reverse-apply to the candidate",
            )
            target_lines[
                index:(
                    replacement_end
                    if replacement_end is not None
                    else index + len(new_run)
                )
            ] = old_run
        target.write_text("".join(target_lines), encoding="utf-8")


def _is_ordered_subsequence(
    expected: Sequence[str],
    observed: Sequence[str],
) -> bool:
    if not expected:
        return True
    position = 0
    for line in observed:
        if line == expected[position]:
            position += 1
            if position == len(expected):
                return True
    return False


def _validate_reverse_applicable_historical_patch(
    *,
    root: Path,
    patch_path: Path,
    patch_blobs: Mapping[str, tuple[str, str]],
    label: str,
) -> frozenset[str]:
    exact_postimages = frozenset(
        relative
        for relative, (_, expected_new) in patch_blobs.items()
        if _git_blob_sha1(
            _input_file(
                root / relative,
                label=f"{label} target {relative}",
            )
        ).startswith(expected_new)
    )
    with tempfile.TemporaryDirectory(
        prefix="xiaoro-historical-patch-check-",
    ) as temporary_name:
        temporary = Path(temporary_name)
        patch_paths = {
            str(match.group(1))
            for match in re.finditer(
                r"^diff --git a/(.+?) b/\1$",
                patch_path.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
        }
        _require(bool(patch_paths), f"{label} has no file sections")
        for relative in patch_paths:
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / relative, target)
        _reverse_apply_historical_patch_descendant(
            root=temporary,
            patch_path=patch_path,
            label=label,
        )
    return exact_postimages


def _run_reclassification_pytest(
    *,
    root: Path,
    nodes: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in (
        "PYTEST_ADDOPTS",
        "PYTEST_CURRENT_TEST",
        "XIAORO_ZERO_API_NETWORK_REPORT",
    ):
        environment.pop(name, None)
    environment["PYTHONPATH"] = str(root)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            *nodes,
        ],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def validate_zero_card_feedback_repair_evidence(
    *,
    repair_files: Mapping[str, str | Path],
    repo_root: str | Path,
) -> dict[str, object]:
    resolved_root = Path(repo_root).resolve()
    resolved_repair_files = {
        name: Path(path).resolve()
        for name, path in repair_files.items()
    }
    _require(
        set(resolved_repair_files)
        == {
            "pre_fix_reproduction",
            "post_fix_verification",
            "focused_zero_api",
            "repair_patch",
        },
        "repair evidence file inventory is invalid",
    )
    pre = _junit_inventory(
        resolved_repair_files["pre_fix_reproduction"],
        label="repair RED JUnit evidence",
    )
    post = _junit_inventory(
        resolved_repair_files["post_fix_verification"],
        label="repair GREEN JUnit evidence",
    )
    focused = _junit_inventory(
        resolved_repair_files["focused_zero_api"],
        label="repair focused JUnit evidence",
    )
    pre_statuses = pre["statuses"]
    post_statuses = post["statuses"]
    focused_statuses = focused["statuses"]
    _require(
        pre_statuses
        == {RECLASSIFICATION_REGRESSION_NODE: "failure"},
        "repair RED JUnit regression node is invalid",
    )
    red_failure = pre["failure_text"].get(
        RECLASSIFICATION_REGRESSION_NODE,
        "",
    )
    _require(
        "inlineProducts.length > 0" in red_failure
        and "tests/guide/runtime/test_feedback_frontend.py"
        in red_failure,
        "repair RED JUnit failure is not the feedback eligibility regression",
    )
    _require(
        post_statuses
        == {
            RECLASSIFICATION_REGRESSION_NODE: "passed",
            RECLASSIFICATION_CONTROL_NODE: "passed",
        },
        "repair GREEN JUnit node inventory is invalid",
    )
    focused_modules = {
        node_id.split("::", 1)[0]
        for node_id in focused_statuses
    }
    _require(
        focused["tests"] == RECLASSIFICATION_FOCUSED_TEST_COUNT
        and focused["failures"] == 0
        and focused["errors"] == 0
        and focused["skipped"] == 0
        and set(focused_statuses.values()) == {"passed"}
        and focused_modules == RECLASSIFICATION_FOCUSED_MODULES
        and RECLASSIFICATION_REGRESSION_NODE in focused_statuses
        and RECLASSIFICATION_CONTROL_NODE in focused_statuses,
        "focused JUnit node inventory is invalid",
    )
    current_nodes = set(
        _collect_pytest_nodes(
            resolved_root,
            tuple(sorted(RECLASSIFICATION_FOCUSED_MODULES)),
        )
    )
    external_post_evidence_nodes = tuple(
        sorted(
            node
            for node in RECLASSIFICATION_POST_EVIDENCE_NODES
            if node.split("::", 1)[0]
            not in RECLASSIFICATION_FOCUSED_MODULES
        )
    )
    if external_post_evidence_nodes:
        current_nodes.update(
            _collect_pytest_nodes(
                resolved_root,
                external_post_evidence_nodes,
            )
        )
    _require(
        RECLASSIFICATION_POST_EVIDENCE_NODES <= current_nodes
        and RECLASSIFICATION_REPLACED_EVIDENCE_NODES
        <= set(focused_statuses)
        and (
            current_nodes - RECLASSIFICATION_POST_EVIDENCE_NODES
            == (
                set(focused_statuses)
                - RECLASSIFICATION_REPLACED_EVIDENCE_NODES
            )
        ),
        "focused JUnit node inventory is invalid",
    )

    patch_path = _input_file(
        resolved_repair_files["repair_patch"],
        label="repair patch",
    )
    _require(
        _digest_file(patch_path) == RECLASSIFICATION_PATCH_SHA256,
        "repair patch does not reverse-apply to the candidate",
    )
    patch_text = patch_path.read_text(encoding="utf-8")
    sections = [
        section
        for section in re.split(
            r"(?=^diff --git )",
            patch_text,
            flags=re.MULTILINE,
        )
        if section
    ]
    patch_blobs: dict[str, tuple[str, str]] = {}
    for section in sections:
        header = re.match(
            r"diff --git a/(.+?) b/(.+?)\n",
            section,
        )
        _require(
            header is not None and header.group(1) == header.group(2),
            "repair patch path identity is invalid",
        )
        path = str(header.group(1))
        index = re.search(
            r"^index ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})(?: \d+)?$",
            section,
            re.MULTILINE,
        )
        _require(
            index is not None
            and re.search(r"^@@ ", section, re.MULTILINE) is not None
            and re.search(
                r"^[+-](?![+-]{2})",
                section,
                re.MULTILINE,
            )
            is not None,
            "repair patch has no bound content hunk",
        )
        patch_blobs[path] = (
            str(index.group(1)),
            str(index.group(2)),
        )
    _require(
        set(patch_blobs) == RECLASSIFICATION_PATCH_PATHS
        and "inlineProducts.length > 0" in patch_text,
        "repair patch is not limited to shared frontend eligibility",
    )
    exact_postimages = _validate_reverse_applicable_historical_patch(
        root=resolved_root,
        patch_path=patch_path,
        patch_blobs=patch_blobs,
        label="repair patch",
    )
    with tempfile.TemporaryDirectory(
        prefix="xiaoro-reclassification-",
    ) as temporary_name:
        temporary = Path(temporary_name)
        for relative in RECLASSIFICATION_PATCH_PATHS:
            source = resolved_root / relative
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        post_run = _run_reclassification_pytest(
            root=temporary,
            nodes=(
                RECLASSIFICATION_REGRESSION_NODE,
                RECLASSIFICATION_CONTROL_NODE,
            ),
        )
        _require(
            post_run.returncode == 0
            and "2 passed" in post_run.stdout,
            "repair patch post-fix regression does not pass independently",
        )
        _reverse_apply_historical_patch_descendant(
            root=temporary,
            patch_path=patch_path,
            label="repair patch",
        )
        preimage_blobs = {
            relative: _git_blob_sha1(temporary / relative)
            for relative in RECLASSIFICATION_PATCH_PATHS
        }
        _require(
            all(
                preimage_blobs[relative].startswith(expected_old)
                for relative, (
                    expected_old,
                    _,
                ) in patch_blobs.items()
                if relative in exact_postimages
            ),
            "repair patch preimage blob binding is invalid",
        )
        shutil.copy2(
            resolved_root
            / "tests/guide/runtime/test_feedback_frontend.py",
            temporary
            / "tests/guide/runtime/test_feedback_frontend.py",
        )
        pre_run = _run_reclassification_pytest(
            root=temporary,
            nodes=(RECLASSIFICATION_REGRESSION_NODE,),
        )
        combined_pre_output = pre_run.stdout + pre_run.stderr
        _require(
            pre_run.returncode == 1
            and "1 failed" in pre_run.stdout
            and (
                "test_feedback_target_lookup_requires_terminal_visible_products"
                in combined_pre_output
            )
            and "inlineProducts.length > 0" in combined_pre_output,
            "repair patch pre-fix regression does not fail independently",
        )

    focused_nodes = tuple(sorted(focused_statuses))
    return {
        "regression_node": RECLASSIFICATION_REGRESSION_NODE,
        "control_node": RECLASSIFICATION_CONTROL_NODE,
        "pre_fix_test_count": pre["tests"],
        "post_fix_test_count": post["tests"],
        "focused_test_count": focused["tests"],
        "focused_module_count": len(focused_modules),
        "focused_node_inventory_sha256": sha256(
            _canonical_json_bytes(focused_nodes)
        ).hexdigest(),
        "patch_preimage_blob_sha1_by_path": {
            relative: preimage_blobs[relative]
            for relative in sorted(preimage_blobs)
        },
        "patch_postimage_blob_sha1_by_path": {
            relative: _git_blob_sha1(resolved_root / relative)
            for relative in sorted(RECLASSIFICATION_PATCH_PATHS)
        },
        "exact_historical_postimage_paths": sorted(exact_postimages),
        "live_red_exit_code": pre_run.returncode,
        "live_green_exit_code": post_run.returncode,
    }


def validate_persisted_image_planning_repair_evidence(
    *,
    repair_files: Mapping[str, str | Path],
    repo_root: str | Path,
) -> dict[str, object]:
    resolved_root = Path(repo_root).resolve()
    resolved_repair_files = {
        name: Path(path).resolve()
        for name, path in repair_files.items()
    }
    _require(
        set(resolved_repair_files)
        == {
            "pre_fix_reproduction",
            "post_fix_verification",
            "focused_zero_api",
            "repair_patch",
        },
        "planning-state repair evidence file inventory is invalid",
    )
    pre = _junit_inventory(
        resolved_repair_files["pre_fix_reproduction"],
        label="planning-state RED JUnit evidence",
    )
    post = _junit_inventory(
        resolved_repair_files["post_fix_verification"],
        label="planning-state GREEN JUnit evidence",
    )
    focused = _junit_inventory(
        resolved_repair_files["focused_zero_api"],
        label="planning-state focused JUnit evidence",
    )
    pre_statuses = pre["statuses"]
    post_statuses = post["statuses"]
    focused_statuses = focused["statuses"]
    _require(
        pre_statuses
        == {PLANNING_RECLASSIFICATION_REGRESSION_NODE: "failure"},
        "planning-state RED JUnit regression node is invalid",
    )
    red_failure = pre["failure_text"].get(
        PLANNING_RECLASSIFICATION_REGRESSION_NODE,
        "",
    )
    _require(
        "committed owner does not match the observed processor"
        in red_failure
        and "test_persisted_image_similarity_prepares_scenario_inputs"
        in red_failure,
        "planning-state RED JUnit does not reproduce the owner failure",
    )
    _require(
        post_statuses
        == {PLANNING_RECLASSIFICATION_REGRESSION_NODE: "passed"},
        "planning-state GREEN JUnit node inventory is invalid",
    )
    _require(
        focused["tests"]
        == len(PLANNING_RECLASSIFICATION_FOCUSED_NODES)
        and focused["failures"] == 0
        and focused["errors"] == 0
        and focused["skipped"] == 0
        and focused_statuses
        == {
            node: "passed"
            for node in PLANNING_RECLASSIFICATION_FOCUSED_NODES
        },
        "planning-state focused JUnit node inventory is invalid",
    )
    current_nodes = set(
        _collect_pytest_nodes(
            resolved_root,
            tuple(
                sorted(
                    {
                        node_id.split("::", 1)[0]
                        for node_id
                        in PLANNING_RECLASSIFICATION_FOCUSED_NODES
                    }
                )
            ),
        )
    )
    _require(
        PLANNING_RECLASSIFICATION_FOCUSED_NODES <= current_nodes,
        "planning-state focused JUnit node inventory is invalid",
    )

    patch_path = _input_file(
        resolved_repair_files["repair_patch"],
        label="planning-state repair patch",
    )
    _require(
        _digest_file(patch_path)
        == PLANNING_RECLASSIFICATION_PATCH_SHA256,
        "planning-state repair patch does not reverse-apply to the candidate",
    )
    patch_text = patch_path.read_text(encoding="utf-8")
    sections = [
        section
        for section in re.split(
            r"(?=^diff --git )",
            patch_text,
            flags=re.MULTILINE,
        )
        if section
    ]
    patch_blobs: dict[str, tuple[str, str]] = {}
    for section in sections:
        header = re.match(
            r"diff --git a/(.+?) b/(.+?)\n",
            section,
        )
        _require(
            header is not None and header.group(1) == header.group(2),
            "planning-state repair patch path identity is invalid",
        )
        relative = str(header.group(1))
        index = re.search(
            r"^index ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})(?: \d+)?$",
            section,
            re.MULTILINE,
        )
        _require(
            index is not None
            and re.search(r"^@@ ", section, re.MULTILINE) is not None
            and re.search(
                r"^[+-](?![+-]{2})",
                section,
                re.MULTILINE,
            )
            is not None,
            "planning-state repair patch has no bound content hunk",
        )
        patch_blobs[relative] = (
            str(index.group(1)),
            str(index.group(2)),
        )
    _require(
        set(patch_blobs) == PLANNING_RECLASSIFICATION_PATCH_PATHS
        and "understanding.goal.value == \"image_similarity\""
        in patch_text
        and "_confirmed_image_product_ids(snapshot)" in patch_text
        and PLANNING_RECLASSIFICATION_REGRESSION_NODE.rsplit(
            "::",
            1,
        )[1]
        in patch_text,
        "planning-state repair patch is not limited to the shared owner",
    )
    exact_postimages = _validate_reverse_applicable_historical_patch(
        root=resolved_root,
        patch_path=patch_path,
        patch_blobs=patch_blobs,
        label="planning-state repair patch",
    )

    post_run = _run_reclassification_pytest(
        root=resolved_root,
        nodes=(PLANNING_RECLASSIFICATION_REGRESSION_NODE,),
    )
    _require(
        post_run.returncode == 0 and "1 passed" in post_run.stdout,
        "planning-state post-fix regression does not pass independently",
    )
    with tempfile.TemporaryDirectory(
        prefix="xiaoro-planning-reclassification-",
    ) as temporary_name:
        temporary = Path(temporary_name)
        for relative in ("app", "tests", "tools", "data"):
            source = resolved_root / relative
            if source.is_dir():
                shutil.copytree(source, temporary / relative)
        selection_audit = (
            resolved_root / "docs/audits/selection-concepts"
        )
        if selection_audit.is_dir():
            shutil.copytree(
                selection_audit,
                temporary / "docs/audits/selection-concepts",
            )
        knowledge_profile = (
            resolved_root
            / "docs/audits/general-knowledge/retrieval_profiles_v1.jsonl"
        )
        knowledge_profile_target = (
            temporary
            / "docs/audits/general-knowledge/retrieval_profiles_v1.jsonl"
        )
        knowledge_profile_target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(knowledge_profile, knowledge_profile_target)
        _reverse_apply_historical_patch_descendant(
            root=temporary,
            patch_path=patch_path,
            label="planning-state repair patch",
        )
        preimage_blobs = {
            relative: _git_blob_sha1(temporary / relative)
            for relative in PLANNING_RECLASSIFICATION_PATCH_PATHS
        }
        _require(
            all(
                preimage_blobs[relative].startswith(expected_old)
                for relative, (
                    expected_old,
                    _,
                ) in patch_blobs.items()
                if relative in exact_postimages
            ),
            "planning-state repair patch preimage blob binding is invalid",
        )
        regression_test_path = (
            "tests/guide/tools/test_task11_production_path_matrix.py"
        )
        shutil.copy2(
            resolved_root / regression_test_path,
            temporary / regression_test_path,
        )
        pre_run = _run_reclassification_pytest(
            root=temporary,
            nodes=(PLANNING_RECLASSIFICATION_REGRESSION_NODE,),
        )
        combined_pre_output = pre_run.stdout + pre_run.stderr
        live_preimage_outcome = (
            "historical_red"
            if (
                pre_run.returncode == 1
                and "1 failed" in pre_run.stdout
                and (
                    "committed owner does not match the observed processor"
                    in combined_pre_output
                )
            )
            else (
                "descendant_red"
                if (
                    pre_run.returncode == 1
                    and "1 failed" in pre_run.stdout
                    and (
                        PLANNING_RECLASSIFICATION_REGRESSION_NODE.rsplit(
                            "::",
                            1,
                        )[1]
                        in combined_pre_output
                    )
                )
                else (
                    "superseded_green"
                    if (
                        pre_run.returncode == 0
                        and "1 passed" in pre_run.stdout
                    )
                    else None
                )
            )
        )
        _require(
            live_preimage_outcome is not None,
            "planning-state pre-fix regression is neither historical RED "
            "nor a validated superseded GREEN",
        )

    focused_nodes = tuple(sorted(focused_statuses))
    return {
        "regression_node": PLANNING_RECLASSIFICATION_REGRESSION_NODE,
        "pre_fix_test_count": pre["tests"],
        "post_fix_test_count": post["tests"],
        "focused_test_count": focused["tests"],
        "focused_node_inventory_sha256": sha256(
            _canonical_json_bytes(focused_nodes)
        ).hexdigest(),
        "patch_preimage_blob_sha1_by_path": preimage_blobs,
        "patch_postimage_blob_sha1_by_path": {
            relative: _git_blob_sha1(resolved_root / relative)
            for relative in sorted(PLANNING_RECLASSIFICATION_PATCH_PATHS)
        },
        "exact_historical_postimage_paths": sorted(exact_postimages),
        "live_preimage_outcome": live_preimage_outcome,
        "historical_red_evidence_preserved": True,
        "live_red_exit_code": pre_run.returncode,
        "live_green_exit_code": post_run.returncode,
    }


def validate_runtime_shell_lease_repair_evidence(
    *,
    repair_files: Mapping[str, str | Path],
    repo_root: str | Path,
) -> dict[str, object]:
    resolved_root = Path(repo_root).resolve()
    resolved_repair_files = {
        name: Path(path).resolve()
        for name, path in repair_files.items()
    }
    _require(
        set(resolved_repair_files)
        == {
            "pre_fix_reproduction",
            "post_fix_verification",
            "focused_zero_api",
            "repair_patch",
        },
        "runtime-gate repair evidence file inventory is invalid",
    )
    pre = _junit_inventory(
        resolved_repair_files["pre_fix_reproduction"],
        label="runtime-gate RED JUnit evidence",
    )
    post = _junit_inventory(
        resolved_repair_files["post_fix_verification"],
        label="runtime-gate GREEN JUnit evidence",
    )
    focused = _junit_inventory(
        resolved_repair_files["focused_zero_api"],
        label="runtime-gate focused JUnit evidence",
    )
    expected_failures = {
        node: "failure"
        for node in RUNTIME_SHELL_REPAIR_REGRESSION_NODES
    }
    expected_passes = {
        node: "passed"
        for node in RUNTIME_SHELL_REPAIR_REGRESSION_NODES
    }
    _require(
        pre["statuses"] == expected_failures
        and all(
            node.rsplit("::", 1)[1]
            in pre["failure_text"].get(node, "")
            for node in RUNTIME_SHELL_REPAIR_REGRESSION_NODES
        ),
        "runtime-gate RED JUnit evidence is invalid",
    )
    _require(
        post["statuses"] == expected_passes,
        "runtime-gate GREEN JUnit evidence is invalid",
    )
    focused_statuses = focused["statuses"]
    focused_modules = {
        node.split("::", 1)[0]
        for node in focused_statuses
    }
    current_nodes = set(
        _collect_pytest_nodes(
            resolved_root,
            tuple(sorted(RUNTIME_SHELL_REPAIR_FOCUSED_MODULES)),
        )
    )
    _require(
        focused["failures"] == 0
        and focused["errors"] == 0
        and focused["skipped"] == 0
        and set(focused_statuses.values()) == {"passed"}
        and focused_modules
        == RUNTIME_SHELL_REPAIR_HISTORICAL_FOCUSED_MODULES
        and focused_modules <= RUNTIME_SHELL_REPAIR_FOCUSED_MODULES
        and set(RUNTIME_SHELL_REPAIR_RENAMED_EVIDENCE_NODES)
        <= set(focused_statuses)
        and (
            set(focused_statuses)
            - set(RUNTIME_SHELL_REPAIR_RENAMED_EVIDENCE_NODES)
        )
        <= current_nodes
        and set(RUNTIME_SHELL_REPAIR_RENAMED_EVIDENCE_NODES.values())
        <= current_nodes
        and RUNTIME_SHELL_REPAIR_REGRESSION_NODES
        <= set(focused_statuses),
        "runtime-gate focused JUnit node inventory is invalid",
    )

    patch_path = _input_file(
        resolved_repair_files["repair_patch"],
        label="runtime-gate repair patch",
    )
    _require(
        _digest_file(patch_path) == RUNTIME_SHELL_REPAIR_PATCH_SHA256,
        "runtime-gate repair patch digest is invalid",
    )
    patch_text = patch_path.read_text(encoding="utf-8")
    sections = [
        section
        for section in re.split(
            r"(?=^diff --git )",
            patch_text,
            flags=re.MULTILINE,
        )
        if section
    ]
    patch_blobs: dict[str, tuple[str, str]] = {}
    for section in sections:
        header = re.match(
            r"diff --git a/(.+?) b/(.+?)\n",
            section,
        )
        _require(
            header is not None and header.group(1) == header.group(2),
            "runtime-gate repair patch path identity is invalid",
        )
        relative = str(header.group(1))
        index = re.search(
            r"^index ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})(?: \d+)?$",
            section,
            re.MULTILINE,
        )
        _require(
            index is not None
            and re.search(r"^@@ ", section, re.MULTILINE) is not None
            and re.search(
                r"^[+-](?![+-]{2})",
                section,
                re.MULTILINE,
            )
            is not None,
            "runtime-gate repair patch has no bound content hunk",
        )
        patch_blobs[relative] = (
            str(index.group(1)),
            str(index.group(2)),
        )
    _require(
        set(patch_blobs) == RUNTIME_SHELL_REPAIR_PATCH_PATHS
        and 'path.startswith("/api/")' in patch_text
        and 'key == "evidence_directory"' in patch_text
        and "_recorded_failure_evidence_binding" in patch_text,
        "runtime-gate repair patch is outside the bounded owner set",
    )
    exact_postimages = frozenset(
        relative
        for relative, (_, expected_new) in patch_blobs.items()
        if _git_blob_sha1(
            _input_file(
                resolved_root / relative,
                label=f"runtime-gate repair target {relative}",
            )
        ).startswith(expected_new)
    )

    post_run = _run_reclassification_pytest(
        root=resolved_root,
        nodes=tuple(sorted(RUNTIME_SHELL_REPAIR_REGRESSION_NODES)),
    )
    _require(
        post_run.returncode == 0 and "2 passed" in post_run.stdout,
        "runtime-gate post-fix regression does not pass independently",
    )
    preimage_blobs: dict[str, str] = {}
    live_red_exit_code: int | None = None
    live_preimage_outcome = "superseded_descendant"
    if exact_postimages == RUNTIME_SHELL_REPAIR_PATCH_PATHS:
        with tempfile.TemporaryDirectory(
            prefix="xiaoro-runtime-gate-reclassification-",
        ) as temporary_name:
            temporary = Path(temporary_name)
            for relative in ("app", "tests", "tools", "data"):
                source = resolved_root / relative
                if source.is_dir():
                    shutil.copytree(source, temporary / relative)
            reverse = subprocess.run(
                [
                    "git",
                    "apply",
                    "--reverse",
                    "--whitespace=nowarn",
                    str(patch_path),
                ],
                cwd=temporary,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            _require(
                reverse.returncode == 0,
                "runtime-gate repair patch does not reverse-apply "
                "to the candidate",
            )
            preimage_blobs = {
                relative: _git_blob_sha1(temporary / relative)
                for relative in RUNTIME_SHELL_REPAIR_PATCH_PATHS
            }
            _require(
                all(
                    preimage_blobs[relative].startswith(expected_old)
                    for relative, (
                        expected_old,
                        _,
                    ) in patch_blobs.items()
                ),
                "runtime-gate repair patch preimage blob binding is invalid",
            )
            pre_run = _run_reclassification_pytest(
                root=temporary,
                nodes=tuple(sorted(RUNTIME_SHELL_REPAIR_REGRESSION_NODES)),
            )
            combined_pre_output = pre_run.stdout + pre_run.stderr
            _require(
                pre_run.returncode == 1
                and "2 failed" in pre_run.stdout
                and all(
                    node.rsplit("::", 1)[1] in combined_pre_output
                    for node in RUNTIME_SHELL_REPAIR_REGRESSION_NODES
                ),
                "runtime-gate pre-fix regressions do not fail independently",
            )
            live_red_exit_code = pre_run.returncode
            live_preimage_outcome = "historical_red"
    else:
        ledger_source = (
            resolved_root / "tools/guide_gates/attempt_ledger.py"
        ).read_text(encoding="utf-8")
        runtime_source = (
            resolved_root / "tools/guide_gates/run_bound_runtime.py"
        ).read_text(encoding="utf-8")
        _require(
            "_recorded_failure_evidence_binding" in ledger_source
            and "new_code in _INDEXED_RUNTIME_FAILURE_CODES"
            in ledger_source
            and 'path.startswith("/api/")' in runtime_source
            and "if requires_authority_lease:" in runtime_source
            and "_request_lifecycle_lease" in runtime_source,
            "runtime-gate repair descendant markers are invalid",
        )

    focused_nodes = tuple(sorted(focused_statuses))
    return {
        "regression_nodes": sorted(
            RUNTIME_SHELL_REPAIR_REGRESSION_NODES
        ),
        "regression_node_count": len(
            RUNTIME_SHELL_REPAIR_REGRESSION_NODES
        ),
        "pre_fix_test_count": pre["tests"],
        "post_fix_test_count": post["tests"],
        "focused_test_count": focused["tests"],
        "historical_focused_test_count": focused["tests"],
        "current_focused_test_count": len(current_nodes),
        "focused_module_count": len(focused_modules),
        "focused_node_inventory_sha256": sha256(
            _canonical_json_bytes(focused_nodes)
        ).hexdigest(),
        "patch_preimage_blob_sha1_by_path": preimage_blobs,
        "patch_postimage_blob_sha1_by_path": {
            relative: _git_blob_sha1(resolved_root / relative)
            for relative in sorted(RUNTIME_SHELL_REPAIR_PATCH_PATHS)
        },
        "exact_historical_postimage_paths": sorted(exact_postimages),
        "descendant_postimage_paths": sorted(
            RUNTIME_SHELL_REPAIR_PATCH_PATHS - exact_postimages
        ),
        "historical_red_evidence_preserved": True,
        "live_preimage_outcome": live_preimage_outcome,
        "live_red_exit_code": live_red_exit_code,
        "live_green_exit_code": post_run.returncode,
    }


def validate_runtime_request_authority_repair_evidence(
    *,
    repair_files: Mapping[str, str | Path],
    repo_root: str | Path,
) -> dict[str, object]:
    resolved_root = Path(repo_root).resolve()
    resolved_repair_files = {
        name: Path(path).resolve()
        for name, path in repair_files.items()
    }
    _require(
        set(resolved_repair_files)
        == {
            "pre_fix_reproduction",
            "post_fix_verification",
            "focused_zero_api",
            "repair_patch",
        },
        (
            "runtime request authority repair evidence file inventory "
            "is invalid"
        ),
    )
    pre = _junit_inventory(
        resolved_repair_files["pre_fix_reproduction"],
        label="runtime request authority RED JUnit evidence",
    )
    post = _junit_inventory(
        resolved_repair_files["post_fix_verification"],
        label="runtime request authority GREEN JUnit evidence",
    )
    focused = _junit_inventory(
        resolved_repair_files["focused_zero_api"],
        label="runtime request authority focused JUnit evidence",
    )
    expected_failures = {
        node: "failure"
        for node in RUNTIME_REQUEST_AUTHORITY_REPAIR_REGRESSION_NODES
    }
    expected_passes = {
        node: "passed"
        for node in RUNTIME_REQUEST_AUTHORITY_REPAIR_REGRESSION_NODES
    }
    _require(
        pre["statuses"] == expected_failures
        and all(
            node.rsplit("::", 1)[1]
            in pre["failure_text"].get(node, "")
            for node in RUNTIME_REQUEST_AUTHORITY_REPAIR_REGRESSION_NODES
        ),
        "runtime request authority RED JUnit evidence is invalid",
    )
    _require(
        post["statuses"] == expected_passes,
        "runtime request authority GREEN JUnit evidence is invalid",
    )
    focused_statuses = focused["statuses"]
    focused_modules = {
        node.split("::", 1)[0]
        for node in focused_statuses
    }
    current_nodes = set(
        _collect_pytest_nodes(
            resolved_root,
            tuple(
                sorted(
                    RUNTIME_REQUEST_AUTHORITY_REPAIR_FOCUSED_MODULES
                )
            ),
        )
    )
    _require(
        focused["failures"] == 0
        and focused["errors"] == 0
        and focused["skipped"] == 0
        and set(focused_statuses.values()) == {"passed"}
        and focused_modules
        == RUNTIME_REQUEST_AUTHORITY_REPAIR_FOCUSED_MODULES
        and set(focused_statuses) <= current_nodes
        and RUNTIME_REQUEST_AUTHORITY_REPAIR_REGRESSION_NODES
        <= set(focused_statuses),
        "runtime request authority focused JUnit inventory is invalid",
    )

    patch_path = _input_file(
        resolved_repair_files["repair_patch"],
        label="runtime request authority repair patch",
    )
    patch_text = patch_path.read_text(encoding="utf-8")
    sections = [
        section
        for section in re.split(
            r"(?=^diff --git )",
            patch_text,
            flags=re.MULTILINE,
        )
        if section
    ]
    patch_blobs: dict[str, tuple[str, str]] = {}
    for section in sections:
        header = re.match(
            r"diff --git a/(.+?) b/(.+?)\n",
            section,
        )
        _require(
            header is not None and header.group(1) == header.group(2),
            "runtime request authority patch path identity is invalid",
        )
        relative = str(header.group(1))
        index = re.search(
            r"^index ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})(?: \d+)?$",
            section,
            re.MULTILINE,
        )
        _require(
            index is not None
            and re.search(r"^@@ ", section, re.MULTILINE) is not None
            and re.search(
                r"^[+-](?![+-]{2})",
                section,
                re.MULTILINE,
            )
            is not None,
            "runtime request authority patch has no bound content hunk",
        )
        patch_blobs[relative] = (
            str(index.group(1)),
            str(index.group(2)),
        )
    _require(
        set(patch_blobs)
        == RUNTIME_REQUEST_AUTHORITY_REPAIR_PATCH_PATHS
        and "def validate_runtime_request_authority" in patch_text
        and "def runtime_request_lifecycle_lease" in patch_text
        and "with lifecycle, _ledger_lock" in patch_text
        and "validate_runtime_request_authority" in patch_text
        and "runtime_request_lifecycle_lease" in patch_text,
        "runtime request authority patch is outside the owner boundary",
    )
    exact_postimages = frozenset(
        relative
        for relative, (_, expected_new) in patch_blobs.items()
        if _git_blob_sha1(
            _input_file(
                resolved_root / relative,
                label=(
                    "runtime request authority repair target "
                    f"{relative}"
                ),
            )
        ).startswith(expected_new)
    )
    post_run = _run_reclassification_pytest(
        root=resolved_root,
        nodes=tuple(
            sorted(
                RUNTIME_REQUEST_AUTHORITY_REPAIR_REGRESSION_NODES
            )
        ),
    )
    _require(
        post_run.returncode == 0
        and (
            f"{len(RUNTIME_REQUEST_AUTHORITY_REPAIR_REGRESSION_NODES)} "
            "passed"
        )
        in post_run.stdout,
        (
            "runtime request authority post-fix regressions do not "
            "pass independently"
        ),
    )
    with tempfile.TemporaryDirectory(
        prefix="xiaoro-runtime-authority-reclassification-",
    ) as temporary_name:
        temporary = Path(temporary_name)
        for relative in ("app", "tests", "tools", "data"):
            source = resolved_root / relative
            if source.is_dir():
                shutil.copytree(source, temporary / relative)
        reverse = subprocess.run(
            [
                "git",
                "apply",
                "--reverse",
                "--whitespace=nowarn",
                str(patch_path),
            ],
            cwd=temporary,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        _require(
            reverse.returncode == 0,
            (
                "runtime request authority repair patch does not "
                "reverse-apply to the candidate"
            ),
        )
        preimage_blobs = {
            relative: _git_blob_sha1(temporary / relative)
            for relative in RUNTIME_REQUEST_AUTHORITY_REPAIR_PATCH_PATHS
        }
        _require(
            all(
                preimage_blobs[relative].startswith(expected_old)
                for relative, (
                    expected_old,
                    _,
                ) in patch_blobs.items()
                if relative in exact_postimages
            ),
            (
                "runtime request authority patch preimage blob "
                "binding is invalid"
            ),
        )
        pre_run = _run_reclassification_pytest(
            root=temporary,
            nodes=tuple(
                sorted(
                    RUNTIME_REQUEST_AUTHORITY_REPAIR_REGRESSION_NODES
                )
            ),
        )
        combined_pre_output = pre_run.stdout + pre_run.stderr
        _require(
            pre_run.returncode == 1
            and (
                f"{len(RUNTIME_REQUEST_AUTHORITY_REPAIR_REGRESSION_NODES)} "
                "failed"
            )
            in pre_run.stdout
            and all(
                node.rsplit("::", 1)[1] in combined_pre_output
                for node in RUNTIME_REQUEST_AUTHORITY_REPAIR_REGRESSION_NODES
            ),
            (
                "runtime request authority pre-fix regressions do not "
                "fail independently"
            ),
        )

    focused_nodes = tuple(sorted(focused_statuses))
    return {
        "regression_nodes": sorted(
            RUNTIME_REQUEST_AUTHORITY_REPAIR_REGRESSION_NODES
        ),
        "regression_node_count": len(
            RUNTIME_REQUEST_AUTHORITY_REPAIR_REGRESSION_NODES
        ),
        "pre_fix_test_count": pre["tests"],
        "post_fix_test_count": post["tests"],
        "focused_test_count": focused["tests"],
        "current_focused_test_count": len(current_nodes),
        "focused_module_count": len(focused_modules),
        "focused_node_inventory_sha256": sha256(
            _canonical_json_bytes(focused_nodes)
        ).hexdigest(),
        "patch_sha256": _digest_file(patch_path),
        "patch_preimage_blob_sha1_by_path": preimage_blobs,
        "patch_postimage_blob_sha1_by_path": {
            relative: _git_blob_sha1(resolved_root / relative)
            for relative in sorted(
                RUNTIME_REQUEST_AUTHORITY_REPAIR_PATCH_PATHS
            )
        },
        "exact_historical_postimage_paths": sorted(exact_postimages),
        "descendant_postimage_paths": sorted(
            RUNTIME_REQUEST_AUTHORITY_REPAIR_PATCH_PATHS
            - exact_postimages
        ),
        "live_red_exit_code": pre_run.returncode,
        "live_green_exit_code": post_run.returncode,
    }


def run_failure_reclassification_audit(
    *,
    ledger_path: str | Path,
    attempt_id: str,
    repair_root: str | Path,
    output_path: str | Path,
) -> dict[str, object]:
    ledger_file = _input_file(ledger_path, label="attempt ledger")
    ledger = _load_object(ledger_file, label="attempt ledger")
    _require(
        ledger.get("schema_version") == "guide-smoke-attempt-ledger-v1"
        and type(ledger.get("revision")) is int
        and isinstance(ledger.get("attempts"), list),
        "attempt ledger identity is invalid",
    )
    matches = [
        item
        for item in ledger["attempts"]
        if isinstance(item, dict) and item.get("attempt_id") == attempt_id
    ]
    _require(len(matches) == 1, "failed attempt identity is invalid")
    attempt = matches[0]
    is_zero_card_failure = (
        attempt.get("first_failure_turn_id") == "bounded-text-fit-t1"
        and attempt.get("first_failure_owner") == "planning_state"
        and attempt.get("failure_code") == "AuditBundleError"
    )
    is_persisted_image_planning_failure = (
        attempt.get("first_failure_turn_id")
        == "bounded-image-context-t2"
        and attempt.get("first_failure_owner") == "sse_contract"
        and attempt.get("failure_code") == "GUIDE_INTERNAL_ERROR"
    )
    is_runtime_timeout_failure = (
        attempt.get("first_failure_turn_id")
        == "bounded-runner-startup"
        and attempt.get("first_failure_owner") == "browser_audit"
        and attempt.get("failure_code") == "TimeoutError"
    )
    _require(
        attempt.get("result") == "failed"
        and attempt.get("trajectory_set") == "bounded"
        and (
            is_zero_card_failure
            or is_persisted_image_planning_failure
            or is_runtime_timeout_failure
        )
        and not attempt.get("failure_reclassifications"),
        "attempt is not a supported unresolved failure",
    )

    context_path = _input_file(
        Path(str(attempt.get("context_path"))),
        label="attempt context",
    )
    _require(
        attempt.get("context_sha256") == _digest_file(context_path),
        "attempt context hash mismatch",
    )
    context = _load_object(context_path, label="attempt context")
    allocation_fields = {
        key: attempt.get(key)
        for key in (
            "attempt_id",
            "plan_revision",
            "repair_epoch",
            "retry_authorization_id",
            "code_revision",
            "started_at",
            "trajectory_set",
            "context_path",
        )
    }
    attempt_record_sha256 = sha256(
        _canonical_json_bytes(allocation_fields)
    ).hexdigest()
    _require(
        context.get("attempt_record_sha256")
        == attempt_record_sha256,
        "attempt allocation hash mismatch",
    )
    readiness_path = _input_file(
        Path(str(context.get("readiness_path"))),
        label="attempt readiness",
    )
    readiness_sha256 = _digest_file(readiness_path)
    _require(
        context.get("readiness_sha256") == readiness_sha256,
        "attempt readiness hash mismatch",
    )
    readiness = _load_object(readiness_path, label="attempt readiness")
    protected_payload_sha256 = readiness.get(
        "protected_payload_sha256"
    )
    _require(
        _is_digest(protected_payload_sha256),
        "attempt protected payload hash is invalid",
    )

    evidence_directory = Path(
        str(attempt.get("evidence_directory"))
    ).resolve()
    _require(
        evidence_directory.is_dir()
        and not evidence_directory.is_symlink(),
        "attempt failure evidence directory is invalid",
    )
    is_runtime_shell_failure = False
    is_runtime_version_sync_failure = False
    if is_runtime_timeout_failure:
        attempt_root = context_path.parent
        browser_directory = attempt_root / "browser-desktop"
        evidence_hashes, evidence_bundle_sha256 = (
            _recorded_failure_evidence_digest(
                attempt,
                directory=evidence_directory,
            )
        )
        runner_failure = _load_object(
            browser_directory / "runner-failure.json",
            label="runtime runner failure",
        )
        error_message = str(runner_failure.get("error_message"))
        is_runtime_shell_failure = (
            "Page.goto: Timeout 30000ms exceeded" in error_message
            and "/chat" in error_message
        )
        is_runtime_version_sync_failure = (
            "Page.wait_for_function: Timeout 120000ms exceeded."
            in error_message
        )
        _require(
            is_runtime_shell_failure != is_runtime_version_sync_failure,
            "runtime timeout failure class is invalid",
        )
        expected_evidence_paths = (
            {
                "attempt-context.json",
                "runtime-identity.json",
                "browser-desktop/runner-failure.json",
                "browser-desktop/summary.json",
            }
            if is_runtime_shell_failure
            else {
                "browser-desktop/bounded-text-fit/summary.json",
                "browser-desktop/runner-failure.json",
                "browser-desktop/summary.json",
            }
        )
        _require(
            set(evidence_hashes) == expected_evidence_paths,
            "runtime timeout failure evidence inventory is invalid",
        )
        summary = _load_object(
            browser_directory / "summary.json",
            label="runtime timeout browser summary",
        )
        runtime_identity = _load_object(
            attempt_root / "runtime-identity.json",
            label="runtime timeout identity",
        )
        runtime_attestation = attempt.get("runtime_attestation")
        _require(
            runner_failure
            == {
                "schema_version": "guide-browser-runner-failure-v1",
                "failure_turn_id": "bounded-runner-startup",
                "error_type": "TimeoutError",
                "error_message": runner_failure.get("error_message"),
            }
            and summary.get("schema_version")
            == "guide-mainline-contract-browser-audit-v1"
            and summary.get("trajectory_set") == "bounded"
            and summary.get("viewport") == "desktop"
            and summary.get("trajectories") == []
            and summary.get("turn_count") == 0
            and summary.get("invalid_clarification_count") == 0
            and summary.get("passed") is False
            and runtime_identity.get("schema_version")
            == "guide-bound-runtime-identity-v1"
            and runtime_identity.get("phase") == "bounded"
            and runtime_identity.get("attempt_id") == attempt_id
            and runtime_identity.get("attempt_context_path")
            == str(context_path.resolve())
            and runtime_identity.get("attempt_context_sha256")
            == attempt.get("context_sha256")
            and isinstance(runtime_attestation, dict)
            and runtime_attestation.get("schema_version")
            == "guide-bound-runtime-attestation-v2"
            and runtime_attestation.get("phase") == "bounded"
            and runtime_attestation.get("attempt_id") == attempt_id
            and runtime_attestation.get("attempt_context_sha256")
            == attempt.get("context_sha256")
            and runtime_attestation.get("runtime_identity_path")
            == str(
                (attempt_root / "runtime-identity.json").resolve()
            )
            and runtime_attestation.get("runtime_identity_sha256")
            == _digest_file(attempt_root / "runtime-identity.json"),
            "attempt failure is not the expected runtime timeout",
        )
    else:
        evidence_hashes, evidence_bundle_sha256 = (
            _failure_evidence_digest(evidence_directory)
        )
        request = _load_object(
            evidence_directory / "request.json",
            label="failure request",
        )
        terminal = _load_object(
            evidence_directory / "presentation-contract.json",
            label="failure terminal",
        )
        dom = _load_object(
            evidence_directory / "terminal-dom.json",
            label="failure DOM",
        )
        events = _sse_events(
            (evidence_directory / "stream.sse").read_text(
                encoding="utf-8"
            ),
            label="failure stream",
        )
        names = tuple(name for name, _ in events)
        console = _load_list(
            evidence_directory / "console.json",
            label="failure console",
        )
        network = _load_list(
            evidence_directory / "network.json",
            label="failure network",
        )
    if is_zero_card_failure:
        clarification_events = tuple(
            data for name, data in events if name == "clarify"
        )
        clarification = terminal.get("clarification")
        _require(
            names[0] == "start"
            and names[-1] == "end"
            and names.count("start") == 1
            and names.count("intent") == 1
            and names.count("clarify") == 1
            and names.count("end") == 1
            and "presentation_contract" not in names
            and "message" not in names
            and "error" not in names
            and terminal.get("terminal_kind") == "clarification"
            and isinstance(clarification, dict)
            and clarification_events == (clarification,)
            and clarification.get("clarification_basis")
            == "fit_selection_evidence_gap"
            and clarification.get("intended_responsibility")
            == "recommendation"
            and clarification.get("intended_recommendation_mode") == "fit"
            and clarification.get("fit_gap_stage") == "decision_selection"
            and clarification.get("fit_decision_status")
            == "INSUFFICIENT_FOR_WINNER"
            and clarification.get("fit_public_fact_count") == 0,
            "attempt failure stream is not the expected typed clarification",
        )
        question = clarification.get("question")
        _require(
            isinstance(question, str)
            and bool(question)
            and request.get("turn_id") == "bounded-text-fit-t1"
            and dom.get("request_id") == request.get("request_id")
            and dom.get("terminal_kind") == "clarification"
            and dom.get("presentation_mode") is None
            and dom.get("clarification_message_count") == 1
            and dom.get("legacy_message_count") == 0
            and dom.get("legacy_product_card_count") == 0
            and dom.get("turn_presentation_root_count") == 0
            and dom.get("visible_product_ids") == []
            and dom.get("inline_product_ids") == []
            and dom.get("shelf_product_ids") == []
            and question in str(dom.get("presentation_text", "")),
            "attempt failure DOM is not a valid zero-card clarification",
        )
        _require(
            bool(console)
            and all(
                isinstance(item, dict)
                and item.get("type") == "error"
                and "404 (Not Found)" in str(item.get("text"))
                for item in console
            )
            and network == [],
            "attempt failure is not the zero-card feedback-target 404",
        )
    elif is_persisted_image_planning_failure:
        error_events = tuple(
            data for name, data in events if name == "error"
        )
        error = terminal.get("error")
        request_body = request.get("body")
        previous_stream = _input_file(
            evidence_directory.parent / "t1" / "stream.sse",
            label="previous image turn stream",
        )
        _require(
            _digest_file(previous_stream)
            == PLANNING_PREDECESSOR_STREAM_SHA256,
            "previous image turn stream hash mismatch",
        )
        previous_events = _sse_events(
            previous_stream.read_text(encoding="utf-8"),
            label="previous image turn stream",
        )
        previous_end = [
            data for name, data in previous_events if name == "end"
        ]
        _require(
            names == ("start", "error")
            and terminal.get("terminal_kind") == "error"
            and isinstance(error, dict)
            and error_events == (error,)
            and error.get("error") == "GUIDE_INTERNAL_ERROR"
            and request.get("turn_id") == "bounded-image-context-t2"
            and isinstance(request_body, dict)
            and request_body.get("conversation_version") == 1
            and request.get("request_message")
            == request_body.get("message")
            and request.get("user_message")
            == request_body.get("message")
            and previous_end
            and previous_end[-1].get("conversation_version") == 1,
            "attempt failure is not the persisted-image planning error",
        )
        _require(
            dom.get("request_id") == request.get("request_id")
            and dom.get("terminal_kind") == "error"
            and dom.get("presentation_mode") is None
            and dom.get("legacy_message_count") == 0
            and dom.get("legacy_product_card_count") == 0
            and dom.get("turn_presentation_root_count") == 0
            and dom.get("visible_product_ids") == []
            and dom.get("inline_product_ids") == []
            and dom.get("shelf_product_ids") == []
            and console == []
            and network == [],
            "attempt failure DOM is not the expected fail-closed error",
        )
    if not is_runtime_timeout_failure:
        _validate_png(
            evidence_directory / "screenshot.png",
            viewport="desktop",
            label="failure screenshot",
        )

    repair_directory = Path(repair_root).resolve()
    _require(
        repair_directory.is_dir()
        and not repair_directory.is_symlink()
        and re.fullmatch(r"repair-epoch-\d+", repair_directory.name)
        is not None,
        "repair evidence root is invalid",
    )
    match = re.fullmatch(r"bounded-smoke-(attempt-\d+)", attempt_id)
    _require(match is not None, "bounded attempt ID is invalid")
    prefix = str(match.group(1))
    patch_suffix = (
        "frontend-delivery-repair.patch"
        if is_zero_card_failure
        else (
            "planning-state-repair.patch"
            if is_persisted_image_planning_failure
            else "runtime-gate-repair.patch"
        )
    )
    repair_files = {
        "pre_fix_reproduction": repair_directory
        / f"{prefix}-pre-fix-reproduction.xml",
        "post_fix_verification": repair_directory
        / f"{prefix}-post-fix-verification.xml",
        "focused_zero_api": repair_directory
        / f"{prefix}-focused-zero-api.xml",
        "repair_patch": repair_directory
        / f"{prefix}-{patch_suffix}",
    }
    if is_zero_card_failure:
        repair_proof = validate_zero_card_feedback_repair_evidence(
            repair_files=repair_files,
            repo_root=Path(__file__).resolve().parents[2],
        )
    elif is_persisted_image_planning_failure:
        repair_proof = validate_persisted_image_planning_repair_evidence(
            repair_files=repair_files,
            repo_root=Path(__file__).resolve().parents[2],
        )
    elif is_runtime_version_sync_failure:
        repair_proof = validate_runtime_request_authority_repair_evidence(
            repair_files=repair_files,
            repo_root=Path(__file__).resolve().parents[2],
        )
    else:
        repair_proof = validate_runtime_shell_lease_repair_evidence(
            repair_files=repair_files,
            repo_root=Path(__file__).resolve().parents[2],
        )
    resolved_repair_files = {
        name: str(_input_file(path, label=f"repair evidence {name}"))
        for name, path in repair_files.items()
    }
    repair_hashes = {
        name: _digest_file(Path(path))
        for name, path in resolved_repair_files.items()
    }
    output = Path(output_path).resolve()
    _require(
        output.parent == repair_directory
        and output.name
        == f"{prefix}-failure-reclassification-audit.json",
        "failure reclassification output path is invalid",
    )
    new_owner = (
        "dom_rendering"
        if is_zero_card_failure
        else (
            "planning_state"
            if is_persisted_image_planning_failure
            else "runtime_gate"
        )
    )
    new_code = (
        "zero_card_feedback_target_lookup"
        if is_zero_card_failure
        else (
            "missing_persisted_image_scenario_inputs"
            if is_persisted_image_planning_failure
            else (
                "runtime_version_sync_authority_check_timeout"
                if is_runtime_version_sync_failure
                else "runtime_shell_authority_lease_timeout"
            )
        )
    )
    local_reproduction = (
        (
            "The immutable stream is a valid typed fit clarification with "
            "no cards; its only browser error is the post-terminal 404."
        )
        if is_zero_card_failure
        else (
            (
                "The immutable second image turn starts from conversation "
                "version 1 and returns GUIDE_INTERNAL_ERROR without an end "
                "event; reversing the pre-routing owner patch reproduces "
                "the failure before a successful state commit."
            )
            if is_persisted_image_planning_failure
            else (
                (
                    "The immutable browser runner failure records the first "
                    "conversation-version synchronization timing out before "
                    "the chat POST or any bounded business turn."
                )
                if is_runtime_version_sync_failure
                else (
                    "The immutable browser runner failure records a /chat "
                    "navigation timeout before any bounded business turn."
                )
            )
        )
    )
    shared_owner_repair = (
        (
            "The frontend requests a feedback target only when the "
            "validated terminal contains visible products."
        )
        if is_zero_card_failure
        else (
            (
                "The existing pre-routing plan_task receives persisted "
                "confirmed-image product IDs for an admitted "
                "image_similarity turn before the single Router decision."
            )
            if is_persisted_image_planning_failure
            else (
                (
                    "The runtime verifies complete readiness at startup, "
                    "checks request authority under a short ledger read, "
                    "and uses an independent request-lifecycle barrier "
                    "through FastAPI/SSE cleanup."
                )
                if is_runtime_version_sync_failure
                else (
                    "The runtime keeps signed proof checks on the shell "
                    "while holding the ledger authority lease only for /api "
                    "requests; attempt completion may bind its indexed "
                    "failure subtree."
                )
            )
        )
    )
    report: dict[str, object] = {
        "schema_version": "guide-smoke-failure-reclassification-v1",
        "passed": True,
        "plan_revision": attempt.get("plan_revision"),
        "attempt_id": attempt_id,
        "evidence_directory": str(evidence_directory),
        "first_failure_turn_id": attempt.get("first_failure_turn_id"),
        "code_revision": attempt.get("code_revision"),
        "attempt_context_sha256": attempt.get("context_sha256"),
        "attempt_record_sha256": attempt_record_sha256,
        "readiness_path": str(readiness_path),
        "readiness_sha256": readiness_sha256,
        "protected_payload_sha256": protected_payload_sha256,
        "pre_reclassification_ledger_revision": ledger["revision"],
        "previous_failure_owner": attempt.get("first_failure_owner"),
        "previous_failure_code": attempt.get("failure_code"),
        "first_failure_owner": new_owner,
        "failure_code": new_code,
        "reviewed_evidence_sha256": evidence_hashes,
        "evidence_bundle_sha256": evidence_bundle_sha256,
        "repair_evidence_files": resolved_repair_files,
        "repair_evidence_sha256": repair_hashes,
        "repair_proof": repair_proof,
        "local_reproduction": local_reproduction,
        "focused_test": (
            f"RED={repair_proof['pre_fix_test_count']} tests; "
            f"GREEN={repair_proof['post_fix_test_count']}; "
            f"focused={repair_proof['focused_test_count']}."
        ),
        "shared_owner_repair": shared_owner_repair,
        "conclusion": (
            f"Reclassify the failure from "
            f"{attempt.get('first_failure_owner')}/"
            f"{attempt.get('failure_code')} to {new_owner}/{new_code}."
        ),
        "findings": [],
    }
    _publish_exclusive(output, report)
    return report


def _publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"independent audit already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise FileExistsError(
                f"independent audit already exists: {path}"
            ) from None
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def run_independent_audit(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    semantic_summary_path: str | Path,
    zero_api_summary_path: str | Path,
    single_path_architecture_path: str | Path,
    test_path_audit_path: str | Path,
    network_report_path: str | Path,
    runtime_network_report_path: str | Path,
    production_path_summary_path: str | Path,
    desktop_summary_path: str | Path,
    mobile_summary_path: str | Path,
    output_path: str | Path,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    _require(root.is_dir(), f"repository root is missing: {root}")
    raw_output = Path(output_path)
    if raw_output.exists() or raw_output.is_symlink():
        output = raw_output.absolute()
        raise FileExistsError(f"independent audit already exists: {output}")
    output = raw_output.resolve()

    inputs = {
        "candidate_manifest": _input_file(
            manifest_path,
            label="candidate manifest",
            trusted_root=root,
        ),
        "semantic_summary": _input_file(
            semantic_summary_path,
            label="semantic summary",
            trusted_root=root,
        ),
        "zero_api_summary": _input_file(
            zero_api_summary_path,
            label="zero API summary",
            trusted_root=root,
        ),
        "single_path_architecture": _input_file(
            single_path_architecture_path,
            label="single-path architecture",
            trusted_root=root,
        ),
        "test_path_audit": _input_file(
            test_path_audit_path,
            label="test-path audit",
            trusted_root=root,
        ),
        "network_report": _input_file(
            network_report_path,
            label="network report",
            trusted_root=root,
        ),
        "runtime_network_report": _input_file(
            runtime_network_report_path,
            label="runtime network report",
            trusted_root=root,
        ),
        "production_path_summary": _input_file(
            production_path_summary_path,
            label="production-path summary",
            trusted_root=root,
        ),
        "desktop_summary": _input_file(
            desktop_summary_path,
            label="desktop summary",
            trusted_root=root,
        ),
        "mobile_summary": _input_file(
            mobile_summary_path,
            label="mobile summary",
            trusted_root=root,
        ),
    }
    _require(
        len(set(inputs.values())) == len(inputs),
        "independent audit inputs must be distinct files",
    )
    _require(
        output not in set(inputs.values()),
        "independent audit output aliases an input",
    )
    input_bytes: dict[str, bytes] = {}
    input_payloads: dict[str, dict[str, Any]] = {}
    for role, path in inputs.items():
        try:
            raw = _read_regular_file_once(
                path,
                label=role.replace("_", " "),
            )
            payload = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise Task11IndependentAuditError(
                f"{role.replace('_', ' ')} is invalid"
            ) from exc
        _require(
            isinstance(payload, dict),
            f"{role.replace('_', ' ')} is invalid",
        )
        input_bytes[role] = raw
        input_payloads[role] = payload
    input_hashes = {
        role: sha256(raw).hexdigest()
        for role, raw in input_bytes.items()
    }
    epoch_root = inputs["candidate_manifest"].parent
    manifest_name = inputs["candidate_manifest"].name
    manifest_name_match = re.fullmatch(
        r"task11-candidate-manifest(?P<suffix>-r\d+)?\.json",
        manifest_name,
    )
    _require(
        manifest_name_match is not None,
        "candidate manifest canonical path is invalid",
    )
    runtime_bundle = epoch_root / (
        "runtime-browser-evidence"
        f"{manifest_name_match.group('suffix') or ''}"
    )
    _require(
        output.parent == epoch_root
        and all(
            path.parent == epoch_root
            for role, path in inputs.items()
            if role
            not in {
                "desktop_summary",
                "mobile_summary",
                "candidate_manifest",
                "runtime_network_report",
            }
        )
        and inputs["runtime_network_report"]
        == runtime_bundle / "task11-zero-api-runtime-network.json"
        and inputs["desktop_summary"]
        == runtime_bundle / "fixture-browser-desktop" / "summary.json"
        and inputs["mobile_summary"]
        == runtime_bundle / "fixture-browser-mobile" / "summary.json",
        "independent audit inputs do not belong to one repair epoch",
    )
    manifest = input_payloads["candidate_manifest"]
    protected_payload_hash, diff_hash = _validate_manifest(
        root=root,
        path=inputs["candidate_manifest"],
        payload=manifest,
        raw_bytes=input_bytes["candidate_manifest"],
        expected_manifest_sha256=expected_manifest_sha256,
    )
    _require(
        _repair_epoch(output) == manifest.get("repair_epoch"),
        "independent audit repair epoch does not match candidate manifest",
    )
    task12_execution_hashes = _validate_task12_execution_tools(
        root=root,
        manifest=manifest,
    )
    _validate_governance_source_contracts(
        root=root,
        manifest=manifest,
    )
    _validate_fixture_marker_ownership(root)
    evidence = {
        role: payload
        for role, payload in input_payloads.items()
        if role != "candidate_manifest"
    }

    semantic_cases = root / SEMANTIC_MATRIX_FIXTURE_PATH
    _require(
        SEMANTIC_MATRIX_FIXTURE_PATH
        in manifest.get("fixture_paths", ())
        and semantic_cases.is_file()
        and not semantic_cases.is_symlink(),
        "semantic fixture binding is invalid",
    )
    _validate_semantic_summary(
        evidence["semantic_summary"],
        cases_path=semantic_cases,
    )
    _validate_network_report(evidence["network_report"], runtime=False)
    runtime_identity_hash = _validate_network_report(
        evidence["runtime_network_report"],
        runtime=True,
        candidate_manifest_hash=input_hashes["candidate_manifest"],
    )
    zero_api_test_count = _validate_zero_api_summary(
        evidence["zero_api_summary"],
        manifest=manifest,
        manifest_sha256=input_hashes["candidate_manifest"],
        protected_payload_hash=protected_payload_hash,
        network_report_sha256=input_hashes["network_report"],
    )
    _validate_architecture(
        evidence["single_path_architecture"],
        manifest=manifest,
        protected_payload_hash=protected_payload_hash,
    )
    _scan_production_architecture(root)
    collected_test_count = _validate_test_path(
        evidence["test_path_audit"],
        root=root,
        manifest=manifest,
    )
    _require(
        zero_api_test_count == collected_test_count,
        "zero API pytest count does not match collected node inventory",
    )
    production_cases = root / PRODUCTION_MATRIX_FIXTURE_PATH
    _require(
        PRODUCTION_MATRIX_FIXTURE_PATH
        in manifest.get("fixture_paths", ())
        and production_cases.is_file()
        and not production_cases.is_symlink(),
        "production-path fixture binding is invalid",
    )
    bounded_trajectory_messages = _validate_bounded_trajectory_messages(
        root=root,
        cases_path=production_cases,
    )
    _validate_production_summary(
        evidence["production_path_summary"],
        candidate_manifest_sha256=input_hashes["candidate_manifest"],
        protected_payload_sha256=protected_payload_hash,
        cases_path=production_cases,
    )
    desktop_runtime, desktop_challenge = _validate_browser_summary(
        repo_root=root,
        path=inputs["desktop_summary"],
        payload=evidence["desktop_summary"],
        viewport="desktop",
    )
    mobile_runtime, mobile_challenge = _validate_browser_summary(
        repo_root=root,
        path=inputs["mobile_summary"],
        payload=evidence["mobile_summary"],
        viewport="mobile",
    )
    _require(
        desktop_runtime == mobile_runtime == runtime_identity_hash,
        "network, desktop, and mobile evidence used different runtime "
        "identities",
    )
    _require(
        desktop_challenge != mobile_challenge,
        "desktop and mobile summaries reused a health challenge",
    )
    _validate_runtime_provenance(
        manifest_path=inputs["candidate_manifest"],
        manifest=manifest,
        runtime_report=evidence["runtime_network_report"],
        browser_summaries=(
            (
                inputs["desktop_summary"],
                evidence["desktop_summary"],
            ),
            (
                inputs["mobile_summary"],
                evidence["mobile_summary"],
            ),
        ),
    )

    _require(
        all(
            _read_regular_file_once(
                path,
                label=role.replace("_", " "),
            )
            == input_bytes[role]
            for role, path in inputs.items()
        ),
        "evidence changed during independent audit",
    )
    reviewed_hashes = input_hashes
    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA,
        "passed": True,
        "plan_revision": manifest.get("plan_revision"),
        "repair_epoch": _repair_epoch(output),
        "candidate_manifest_sha256": reviewed_hashes[
            "candidate_manifest"
        ],
        "protected_payload_sha256": protected_payload_hash,
        "production_diff_sha256": diff_hash,
        "task12_execution_tool_sha256": task12_execution_hashes,
        "reviewed_evidence_sha256": reviewed_hashes,
        "checks": {
            "manifest": True,
            "production_diff": True,
            "semantic_summary": True,
            "zero_api_summary": True,
            "single_path_architecture": True,
            "production_bridge_scan": True,
            "task12_execution_tools": True,
            "governance_source_contracts": True,
            "test_path_audit": True,
            "network_report": True,
            "runtime_network_report": True,
            "production_path_summary": True,
            "bounded_trajectory_messages": True,
            "desktop_summary": True,
            "mobile_summary": True,
        },
        "bounded_trajectory_message_count": len(
            bounded_trajectory_messages
        ),
        "finding_count": 0,
        "p0_finding_count": 0,
        "p1_finding_count": 0,
        "findings": [],
    }
    _publish_exclusive(output, report)
    return report


run_task11_independent_audit = run_independent_audit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    parser.add_argument("--semantic-summary", type=Path, required=True)
    parser.add_argument("--zero-api-summary", type=Path, required=True)
    parser.add_argument(
        "--single-path-architecture",
        type=Path,
        required=True,
    )
    parser.add_argument("--test-path-audit", type=Path, required=True)
    parser.add_argument("--network-report", type=Path, required=True)
    parser.add_argument(
        "--runtime-network-report",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--production-path-summary",
        type=Path,
        required=True,
    )
    parser.add_argument("--desktop-summary", type=Path, required=True)
    parser.add_argument("--mobile-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _failure_reclassification_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Derive a bounded-smoke failure reclassification from "
            "immutable evidence."
        )
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--repair-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["audit-failure-reclassification"]:
        args = _failure_reclassification_parser().parse_args(
            arguments[1:]
        )
        report = run_failure_reclassification_audit(
            ledger_path=args.ledger,
            attempt_id=args.attempt_id,
            repair_root=args.repair_root,
            output_path=args.output,
        )
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0
    args = _parser().parse_args(arguments)
    report = run_independent_audit(
        repo_root=args.repo_root,
        manifest_path=args.manifest,
        expected_manifest_sha256=args.expected_manifest_sha256,
        semantic_summary_path=args.semantic_summary,
        zero_api_summary_path=args.zero_api_summary,
        single_path_architecture_path=args.single_path_architecture,
        test_path_audit_path=args.test_path_audit,
        network_report_path=args.network_report,
        runtime_network_report_path=args.runtime_network_report,
        production_path_summary_path=args.production_path_summary,
        desktop_summary_path=args.desktop_summary,
        mobile_summary_path=args.mobile_summary,
        output_path=args.output,
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "REPORT_SCHEMA",
    "Task11IndependentAuditError",
    "run_failure_reclassification_audit",
    "run_independent_audit",
    "run_task11_independent_audit",
    "validate_runtime_request_authority_repair_evidence",
    "validate_runtime_shell_lease_repair_evidence",
    "validate_zero_card_feedback_repair_evidence",
]
