from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
from hashlib import sha256
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from tempfile import gettempdir
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from app.guide.application.public_event_envelope import (
    GuidePublicEventError,
    materialize_guide_public_events,
)
from app.guide.presentation.sse_events import (
    ClarifyEvent,
    PresentationContractEvent,
    SseEvent,
    StartEvent,
)
from app.guide.presentation.terminal_contract_guard import (
    GuideTerminalContractError,
)
from tools.guide_gates.runtime_auth import (
    PROOF_REQUEST_SCHEMA,
    RuntimeProofError,
    verify_runtime_proof,
)


Phase = Literal["bounded", "translation", "browser"]
AttemptResult = Literal["allocated", "consumed", "passed", "failed"]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PHASES = frozenset({"bounded", "translation", "browser"})
_SCHEMA_VERSION = "guide-smoke-attempt-ledger-v1"
_CONTEXT_SCHEMA_VERSION = "guide-smoke-attempt-context-v1"
_RUNTIME_ATTESTATION_SCHEMA_VERSION = (
    "guide-bound-runtime-attestation-v2"
)
_RUNTIME_REGISTRATION_SCHEMA_VERSION = (
    "guide-bound-runtime-registration-v1"
)
_RUNTIME_PROOF_PATH = "/__task11_runtime__/proof"
_RUNTIME_IDENTITY_FILENAME = "runtime-identity.json"
_TERMINAL_RESULTS = frozenset({"passed", "failed"})
_FAILURE_EVIDENCE_FILES = frozenset({
    "request.json",
    "stream.sse",
    "presentation-contract.json",
    "terminal-dom.json",
    "screenshot.png",
    "console.json",
    "network.json",
})
_RECLASSIFICATION_REPAIR_EVIDENCE_KEYS = frozenset({
    "pre_fix_reproduction",
    "post_fix_verification",
    "focused_zero_api",
    "repair_patch",
})
_RECLASSIFICATION_OWNER_BY_CODE = {
    "collecting_consultation_inherited_stale_current_item": "admission",
    "runtime_shell_authority_lease_timeout": "runtime_gate",
    "runtime_version_sync_authority_check_timeout": "runtime_gate",
    "sole_confirmed_image_reference_unbound": "admission",
    "typed_clarification_route_intent_reinterpretation": "dom_rendering",
    "zero_card_feedback_target_lookup": "dom_rendering",
    "invalid_fit_clarification": "planning_state",
    "missing_explore_result_count_default": "planning_state",
    "missing_persisted_image_scenario_inputs": "planning_state",
    "typed_image_action_question_summary_not_projected_to_focus_state": (
        "planning_state"
    ),
}
_ACTIVE_RECLASSIFICATION_CODES = frozenset(
    {
        "runtime_shell_authority_lease_timeout",
        "runtime_version_sync_authority_check_timeout",
        "zero_card_feedback_target_lookup",
        "missing_persisted_image_scenario_inputs",
    }
)
_INDEXED_RUNTIME_FAILURE_CODES = frozenset({
    "runtime_shell_authority_lease_timeout",
    "runtime_version_sync_authority_check_timeout",
})
_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
_LOCK_DIRECTORY = (
    Path(gettempdir()).resolve()
    / "xiaoro-guide-attempt-ledger-locks-v1"
)
_RUNTIME_REQUEST_LOCK_DIRECTORY = (
    Path(gettempdir()).resolve()
    / "xiaoro-guide-runtime-request-locks-v1"
)
_CANONICAL_LEDGER_RELATIVE_PATH = (
    "docs/audits/final-release/mainline-contract-closure/"
    "smoke-attempt-ledger.json"
)
_CHECKPOINT_AUTHORITY_FILENAME = (
    "smoke-attempt-ledger-checkpoint-authority.json"
)
_CHECKPOINT_AUTHORITY_SCHEMA = (
    "guide-smoke-ledger-checkpoint-authority-v1"
)
_AUTHORIZATION_RECEIPT_SCHEMA = (
    "guide-smoke-attempt-authorization-receipt-v1"
)
_AUTHORIZATION_RECEIPT_PREFIX = (
    "smoke-attempt-ledger-authorization-"
)
_ATTEMPT_CONTEXT_WITNESS_PREFIX = (
    "smoke-attempt-ledger-context-"
)
_FINAL_FIXTURE_PATH = (
    "tests/fixtures/guide/final_release/"
    "real_translation_12x4_v5.jsonl"
)
_SEED_IMAGE_ASSETS_PATH = (
    "data/canonical/seed_product_images_v1.jsonl"
)
_BACKEND_REQUIRED_COUNTS = {
    "trajectory_count": 12,
    "critical_trajectory_count": 12,
    "critical_trajectory_passed": 12,
    "expected_turn_count": 48,
    "turn_count": 48,
    "completed_turn_count": 48,
    "passed_turn_count": 48,
    "translation_injection_count": 48,
}
_BACKEND_ZERO_COUNTS = (
    "context_mismatch_count",
    "provider_call_count",
    "copywriter_call_count",
    "message_event_count",
    "wrong_responsibility_count",
    "wrong_binding_count",
    "wrong_product_count",
    "wrong_presentation_count",
    "price_specification_mismatch_count",
    "section_order_violation_count",
    "raw_ad_leak_count",
    "internal_language_count",
    "internal_public_language_count",
    "unsafe_downgrade_count",
    "frontend_contract_violation_count",
    "outbound_network_attempt_count",
    "serious_failure_count",
)
_BACKEND_TRACE_KEYS = frozenset({
    "trajectory_id",
    "turn_id",
    "completed",
    "clarification",
    "translation_injection_count",
    "image_product_ids",
    "image_asset_sha256s",
    "raw_sse_path",
    "raw_sse_sha256",
    "sealed_context_sha256",
    "observed_context_sha256",
    "context_mismatch_count",
    "provider_call_count",
    "copywriter_call_count",
    "presentation_contract_count",
    "message_event_count",
    "wrong_responsibility_count",
    "wrong_binding_count",
    "wrong_product_count",
    "price_specification_mismatch_count",
    "section_order_violation_count",
    "raw_ad_leak_count",
    "internal_language_count",
    "unsafe_downgrade_count",
    "frontend_contract_violation_count",
    "expected_responsibility",
    "actual_responsibility",
    "visible_product_ids",
    "event_names",
    "passed",
})
_BACKEND_TRACE_ZERO_COUNTS = (
    "context_mismatch_count",
    "provider_call_count",
    "copywriter_call_count",
    "message_event_count",
    "wrong_responsibility_count",
    "wrong_binding_count",
    "wrong_product_count",
    "price_specification_mismatch_count",
    "section_order_violation_count",
    "raw_ad_leak_count",
    "internal_language_count",
    "unsafe_downgrade_count",
    "frontend_contract_violation_count",
)
_REVISION_OPERATIONS = frozenset({
    "initialized",
    "legacy_checkpoint",
    "state_checkpoint",
    "compare_and_swap",
    "authorization_created",
    "attempt_allocated",
    "runtime_registered",
    "runtime_registration_aborted",
    "authorization_consumed",
    "attempt_completed",
    "runtime_registration_terminated",
    "failure_reclassified",
})
_STATE_SNAPSHOT_KEYS = frozenset({
    "schema_version",
    "ledger_path",
    "revision",
    "circuit_state",
    "attempts",
    "authorizations",
})
_ATTEMPT_IMMUTABLE_KEYS = frozenset({
    "attempt_id",
    "plan_revision",
    "repair_epoch",
    "retry_authorization_id",
    "code_revision",
    "started_at",
    "trajectory_set",
    "expected_manifest_sha256",
    "evidence_directory",
    "context_path",
    "allocated_ledger_revision",
})
_AUTHORIZATION_IMMUTABLE_KEYS = frozenset({
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
})
_SSE_EVENT_ADAPTER = TypeAdapter(SseEvent)


class AttemptLedgerError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _bound_runtime_endpoint(base_url: str) -> tuple[str, int, str]:
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
        address = ipaddress.ip_address(str(parsed.hostname))
    except ValueError as exc:
        raise AttemptLedgerError(
            "bound runtime base URL is invalid"
        ) from exc
    if (
        parsed.scheme != "http"
        or not address.is_loopback
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise AttemptLedgerError(
            "bound runtime base URL must be loopback HTTP"
        )
    normalized = f"http://{address.compressed}:{port}"
    return address.compressed, port, normalized


def _runtime_proof_request(
    *,
    host: str,
    port: int,
    method: str,
    payload: dict[str, object] | None,
) -> dict[str, object]:
    body = (
        None
        if payload is None
        else json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    connection = http.client.HTTPConnection(host, port, timeout=10)
    try:
        connection.request(
            method,
            _RUNTIME_PROOF_PATH,
            body=body,
            headers=(
                {}
                if body is None
                else {"Content-Type": "application/json"}
            ),
        )
        response = connection.getresponse()
        content = response.read()
    except OSError as exc:
        raise AttemptLedgerError(
            "bound runtime proof request failed"
        ) from exc
    finally:
        connection.close()
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AttemptLedgerError(
            "bound runtime proof response is invalid"
        ) from exc
    if response.status != 200:
        message = (
            decoded.get("error")
            if isinstance(decoded, dict)
            else None
        )
        raise AttemptLedgerError(
            str(message or "bound runtime proof was rejected")
        )
    if not isinstance(decoded, dict):
        raise AttemptLedgerError(
            "bound runtime proof response is invalid"
        )
    return decoded


def _verify_live_bound_runtime_identity(
    *,
    identity_path: Path,
    attempt_context: Path,
    expected_host: str,
    expected_port: int,
) -> dict[str, Any]:
    from tools.guide_gates.run_bound_runtime import (
        BoundRuntimeError,
        verify_bound_runtime_identity,
    )

    try:
        return verify_bound_runtime_identity(
            identity_path=identity_path,
            attempt_context=attempt_context,
            expected_host=expected_host,
            expected_port=expected_port,
        )
    except (BoundRuntimeError, OSError, ValueError) as exc:
        raise AttemptLedgerError(
            "bound runtime identity is invalid"
        ) from exc


def _request_live_runtime_proof(
    *,
    host: str,
    port: int,
    request: dict[str, object],
) -> dict[str, object]:
    return _runtime_proof_request(
        host=host,
        port=port,
        method="POST",
        payload=request,
    )


def _ledger_state_snapshot(
    payload: dict[str, Any],
    *,
    allocation_attempt_id: str | None = None,
) -> dict[str, Any]:
    attempts = deepcopy(payload["attempts"])
    if allocation_attempt_id is not None:
        matches = [
            attempt
            for attempt in attempts
            if (
                isinstance(attempt, dict)
                and attempt.get("attempt_id") == allocation_attempt_id
            )
        ]
        if len(matches) != 1:
            raise AttemptLedgerError(
                "ledger allocation revision is invalid"
            )
        matches[0]["allocated_ledger_hash"] = None
        matches[0]["context_sha256"] = None
    state = {
        "schema_version": payload["schema_version"],
        "ledger_path": payload["ledger_path"],
        "revision": payload["revision"],
        "circuit_state": payload["circuit_state"],
        "attempts": attempts,
        "authorizations": deepcopy(payload["authorizations"]),
    }
    return state


def _ledger_state_sha256(
    payload: dict[str, Any],
    *,
    allocation_attempt_id: str | None = None,
) -> str:
    return sha256(
        _canonical_bytes(
            _ledger_state_snapshot(
                payload,
                allocation_attempt_id=allocation_attempt_id,
            )
        )
    ).hexdigest()


def _legacy_ledger_state_sha256(payload: dict[str, Any]) -> str:
    state = {
        "schema_version": payload["schema_version"],
        "revision": payload["revision"],
        "circuit_state": payload["circuit_state"],
        "attempts": deepcopy(payload["attempts"]),
        "authorizations": deepcopy(payload["authorizations"]),
    }
    return sha256(_canonical_bytes(state)).hexdigest()


def _revision_hash(entry: dict[str, Any]) -> str:
    fields = {
        key: entry.get(key)
        for key in (
            "revision",
            "previous_hash",
            "operation",
            "attempt_id",
            "authorization_id",
            "source_sha256",
            "state_sha256",
        )
    }
    if "state_snapshot" in entry:
        fields["previous_state_sha256"] = entry.get(
            "previous_state_sha256"
        )
        fields["state_snapshot"] = entry.get("state_snapshot")
    return sha256(_canonical_bytes(fields)).hexdigest()


def _append_revision(
    payload: dict[str, Any],
    *,
    operation: str,
    attempt_id: str | None = None,
    authorization_id: str | None = None,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    if operation not in _REVISION_OPERATIONS:
        raise AttemptLedgerError("ledger revision operation is invalid")
    chain = payload.setdefault("revision_chain", [])
    if not isinstance(chain, list):
        raise AttemptLedgerError("ledger revision chain is invalid")
    previous_hash = (
        chain[-1].get("revision_hash")
        if chain and isinstance(chain[-1], dict)
        else None
    )
    allocation_id = (
        attempt_id if operation == "attempt_allocated" else None
    )
    snapshot = _ledger_state_snapshot(
        payload,
        allocation_attempt_id=allocation_id,
    )
    entry = {
        "revision": payload["revision"],
        "previous_hash": previous_hash,
        "operation": operation,
        "attempt_id": attempt_id,
        "authorization_id": authorization_id,
        "source_sha256": source_sha256,
        "state_sha256": sha256(_canonical_bytes(snapshot)).hexdigest(),
        "previous_state_sha256": (
            chain[-1].get("state_sha256")
            if chain and isinstance(chain[-1], dict)
            else None
        ),
        "state_snapshot": snapshot,
    }
    entry["revision_hash"] = _revision_hash(entry)
    chain.append(entry)
    return entry


def _snapshot_record_ids(
    snapshot: Mapping[str, object],
    *,
    collection: str,
    identity_key: str,
) -> tuple[str, ...]:
    records = snapshot.get(collection)
    if not isinstance(records, list):
        raise AttemptLedgerError("ledger state snapshot is invalid")
    identities: list[str] = []
    for record in records:
        identity = (
            record.get(identity_key)
            if isinstance(record, dict)
            else None
        )
        if not isinstance(identity, str) or not identity:
            raise AttemptLedgerError("ledger state snapshot is invalid")
        identities.append(identity)
    if len(identities) != len(set(identities)):
        raise AttemptLedgerError("ledger state snapshot is invalid")
    return tuple(identities)


def _verify_snapshot_extension(
    previous: Mapping[str, object],
    current: Mapping[str, object],
    *,
    entry: Mapping[str, object],
) -> None:
    previous_attempt_ids = _snapshot_record_ids(
        previous,
        collection="attempts",
        identity_key="attempt_id",
    )
    current_attempt_ids = _snapshot_record_ids(
        current,
        collection="attempts",
        identity_key="attempt_id",
    )
    previous_authorization_ids = _snapshot_record_ids(
        previous,
        collection="authorizations",
        identity_key="authorization_id",
    )
    current_authorization_ids = _snapshot_record_ids(
        current,
        collection="authorizations",
        identity_key="authorization_id",
    )
    if (
        current_attempt_ids[: len(previous_attempt_ids)]
        != previous_attempt_ids
        or current_authorization_ids[: len(previous_authorization_ids)]
        != previous_authorization_ids
    ):
        raise AttemptLedgerError(
            "historical ledger state was deleted or reordered"
        )
    operation = entry.get("operation")
    added_attempt_ids = current_attempt_ids[len(previous_attempt_ids) :]
    added_authorization_ids = current_authorization_ids[
        len(previous_authorization_ids) :
    ]
    if (
        bool(added_attempt_ids)
        and (
            operation != "attempt_allocated"
            or added_attempt_ids != (entry.get("attempt_id"),)
        )
    ):
        raise AttemptLedgerError(
            "historical ledger state extension is invalid"
        )
    if (
        bool(added_authorization_ids)
        and (
            operation != "authorization_created"
            or added_authorization_ids
            != (entry.get("authorization_id"),)
        )
    ):
        raise AttemptLedgerError(
            "historical ledger state extension is invalid"
        )
    previous_attempts = previous["attempts"]
    current_attempts = current["attempts"]
    changed_attempt_ids: set[str] = set()
    for old, new in zip(
        previous_attempts,
        current_attempts,
        strict=False,
    ):
        if old == new:
            continue
        changed_attempt_ids.add(str(old["attempt_id"]))
        if any(
            old.get(key) is not None
            and old.get(key) != new.get(key)
            and not (
                key == "evidence_directory"
                and operation == "attempt_completed"
            )
            for key in _ATTEMPT_IMMUTABLE_KEYS
        ):
            raise AttemptLedgerError(
                "historical ledger attempt was rewritten"
            )
    previous_authorizations = previous["authorizations"]
    current_authorizations = current["authorizations"]
    changed_authorization_ids: set[str] = set()
    for old, new in zip(
        previous_authorizations,
        current_authorizations,
        strict=False,
    ):
        if old == new:
            continue
        changed_authorization_ids.add(str(old["authorization_id"]))
        if any(
            old.get(key) is not None and old.get(key) != new.get(key)
            for key in _AUTHORIZATION_IMMUTABLE_KEYS
        ):
            raise AttemptLedgerError(
                "historical ledger authorization was rewritten"
            )
    allowed_attempt_ids = {
        str(entry["attempt_id"])
        for _ in (0,)
        if isinstance(entry.get("attempt_id"), str)
    }
    allowed_authorization_ids = {
        str(entry["authorization_id"])
        for _ in (0,)
        if isinstance(entry.get("authorization_id"), str)
    }
    if (
        not changed_attempt_ids <= allowed_attempt_ids
        or not changed_authorization_ids <= allowed_authorization_ids
    ):
        raise AttemptLedgerError(
            "historical ledger state was rewritten"
        )


def _verify_revision_chain(
    payload: dict[str, Any],
    *,
    allow_uncheckpointed: bool = False,
) -> None:
    chain = payload.get("revision_chain")
    if not isinstance(chain, list) or not chain:
        raise AttemptLedgerError("ledger revision chain is invalid")
    seen_revisions: set[int] = set()
    seen_hashes: set[str] = set()
    previous_revision: int | None = None
    previous_hash: str | None = None
    previous_snapshot: Mapping[str, object] | None = None
    snapshot_started = False
    for index, entry in enumerate(chain):
        if not isinstance(entry, dict):
            raise AttemptLedgerError("ledger revision chain is invalid")
        revision = entry.get("revision")
        revision_hash = entry.get("revision_hash")
        if (
            not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 0
            or revision in seen_revisions
            or not _is_sha256(revision_hash)
            or revision_hash in seen_hashes
            or entry.get("operation") not in _REVISION_OPERATIONS
            or not _is_sha256(entry.get("state_sha256"))
            or entry.get("previous_hash") != previous_hash
            or (
                index > 0
                and previous_revision is not None
                and revision != previous_revision + 1
            )
            or _revision_hash(entry) != revision_hash
        ):
            raise AttemptLedgerError("ledger revision chain is invalid")
        if index == 0 and entry.get("previous_hash") is not None:
            raise AttemptLedgerError("ledger revision chain is invalid")
        operation = entry.get("operation")
        source_sha256 = entry.get("source_sha256")
        if (
            operation in {"legacy_checkpoint", "state_checkpoint"}
            and not _is_sha256(source_sha256)
        ):
            raise AttemptLedgerError(
                "ledger revision chain checkpoint is invalid"
            )
        if (
            operation == "authorization_consumed"
            and source_sha256 is not None
            and not _is_sha256(source_sha256)
        ):
            raise AttemptLedgerError(
                "ledger runtime attestation hash is invalid"
            )
        if (
            operation not in {
                "legacy_checkpoint",
                "state_checkpoint",
                "authorization_consumed",
            }
            and source_sha256 is not None
        ):
            raise AttemptLedgerError("ledger revision chain is invalid")
        snapshot = entry.get("state_snapshot")
        has_snapshot = "state_snapshot" in entry
        if has_snapshot:
            if (
                not isinstance(snapshot, dict)
                or set(snapshot) != _STATE_SNAPSHOT_KEYS
                or snapshot.get("schema_version") != _SCHEMA_VERSION
                or snapshot.get("ledger_path")
                != payload.get("ledger_path")
                or snapshot.get("revision") != revision
                or snapshot.get("circuit_state")
                not in {"closed", "open"}
                or not isinstance(snapshot.get("attempts"), list)
                or not isinstance(snapshot.get("authorizations"), list)
                or sha256(_canonical_bytes(snapshot)).hexdigest()
                != entry.get("state_sha256")
                or entry.get("previous_state_sha256")
                != (
                    chain[index - 1].get("state_sha256")
                    if index > 0
                    else None
                )
                or (
                    not snapshot_started
                    and index > 0
                    and operation != "state_checkpoint"
                )
            ):
                raise AttemptLedgerError(
                    "ledger revision state snapshot is invalid"
                )
            if previous_snapshot is not None:
                _verify_snapshot_extension(
                    previous_snapshot,
                    snapshot,
                    entry=entry,
                )
            snapshot_started = True
            previous_snapshot = snapshot
        elif snapshot_started:
            raise AttemptLedgerError(
                "ledger revision state snapshot is missing"
            )
        seen_revisions.add(revision)
        seen_hashes.add(str(revision_hash))
        previous_revision = revision
        previous_hash = str(revision_hash)
    tip = chain[-1]
    if tip["revision"] != payload["revision"]:
        raise AttemptLedgerError("ledger revision chain tip is invalid")
    if not snapshot_started:
        if not allow_uncheckpointed:
            raise AttemptLedgerError(
                "ledger requires an append-only state checkpoint"
            )
        if tip["state_sha256"] != _legacy_ledger_state_sha256(payload):
            raise AttemptLedgerError(
                "ledger revision chain state is invalid"
            )
        return
    allocation_attempt_id = (
        str(tip["attempt_id"])
        if (
            tip.get("operation") == "attempt_allocated"
            and isinstance(tip.get("attempt_id"), str)
        )
        else None
    )
    current_snapshot = _ledger_state_snapshot(
        payload,
        allocation_attempt_id=allocation_attempt_id,
    )
    if (
        tip.get("state_snapshot") != current_snapshot
        or tip["state_sha256"]
        != sha256(_canonical_bytes(current_snapshot)).hexdigest()
    ):
        raise AttemptLedgerError("ledger revision chain state is invalid")


def ledger_anchor(payload: dict[str, Any]) -> dict[str, object]:
    _validate_ledger(payload)
    tip = payload["revision_chain"][-1]
    return {
        "revision": tip["revision"],
        "revision_hash": tip["revision_hash"],
    }


def verify_ledger_extension(
    payload: dict[str, Any],
    *,
    anchor_revision: object,
    anchor_hash: object,
) -> None:
    _validate_ledger(payload)
    matches = [
        entry
        for entry in payload["revision_chain"]
        if (
            entry.get("revision") == anchor_revision
            and entry.get("revision_hash") == anchor_hash
        )
    ]
    if len(matches) != 1:
        raise AttemptLedgerError(
            "ledger does not extend the sealed anchor"
        )


def _failure_evidence_sha256(directory: Path) -> str:
    digest = sha256()
    for name in sorted(_FAILURE_EVIDENCE_FILES):
        path = directory / name
        if not path.is_file():
            raise AttemptLedgerError(
                "failure reclassification evidence is missing"
            )
        name_bytes = name.encode("utf-8")
        content = path.read_bytes()
        digest.update(str(len(name_bytes)).encode("ascii"))
        digest.update(b":")
        digest.update(name_bytes)
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b":")
        digest.update(content)
    return digest.hexdigest()


def _recorded_failure_evidence_binding(
    attempt: Mapping[str, object],
    *,
    evidence_directory: Path,
) -> tuple[dict[str, str], str]:
    manifest = attempt.get("terminal_evidence")
    context_path = Path(str(attempt.get("context_path"))).resolve()
    output_directory = context_path.parent
    if (
        not isinstance(manifest, dict)
        or Path(str(manifest.get("root"))).resolve()
        != evidence_directory.resolve()
    ):
        raise AttemptLedgerError(
            "failure reclassification evidence mismatch"
        )
    _require_recorded_terminal_evidence_manifest(
        manifest,
        output_directory=output_directory,
    )
    raw_hashes = manifest.get("sha256_by_path")
    if not isinstance(raw_hashes, dict):
        raise AttemptLedgerError(
            "failure reclassification evidence mismatch"
        )
    hashes = {
        str(relative): str(expected_sha256)
        for relative, expected_sha256 in raw_hashes.items()
    }
    digest = sha256()
    for relative, expected_sha256 in sorted(hashes.items()):
        content = (output_directory / relative).read_bytes()
        if sha256(content).hexdigest() != expected_sha256:
            raise AttemptLedgerError(
                "failure reclassification evidence mismatch"
            )
        name_bytes = relative.encode("utf-8")
        digest.update(str(len(name_bytes)).encode("ascii"))
        digest.update(b":")
        digest.update(name_bytes)
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b":")
        digest.update(content)
    return hashes, digest.hexdigest()


def _attempt_allocation_sha256(attempt: dict[str, Any]) -> str:
    fields = {
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
    return sha256(_canonical_bytes(fields)).hexdigest()


def ledger_temp_path(path: str | Path) -> Path:
    ledger = Path(path)
    return ledger.with_name(f".{ledger.name}.tmp")


def _ledger_temp_prefix(path: Path) -> str:
    return f".{path.name}.tmp-"


def _new_ledger_temp_path(path: Path) -> Path:
    return path.with_name(
        f"{_ledger_temp_prefix(path)}{secrets.token_hex(16)}"
    )


def _canonical_ledger_path(path: str | Path) -> Path:
    supplied = Path(path).expanduser()
    canonical = Path(os.path.abspath(supplied))
    current = Path(canonical.anchor)
    try:
        for component in canonical.parts[1:]:
            current /= component
            try:
                metadata = os.lstat(current)
            except FileNotFoundError:
                break
            if stat.S_ISLNK(metadata.st_mode):
                raise AttemptLedgerError(
                    "ledger path contains a symlink alias"
                )
    except OSError as exc:
        raise AttemptLedgerError("ledger path is invalid") from exc
    return canonical


@dataclass(frozen=True)
class _BoundLedgerPath:
    path: Path
    parent_descriptor: int
    parent_identity: tuple[int, int]

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class _BoundLockFile:
    root_descriptor: int
    root_identity: tuple[int, int]
    directory_descriptor: int
    directory_identity: tuple[int, int]
    file_descriptor: int
    file_identity: tuple[int, int]
    name: str


def _open_directory_descriptor(
    directory: Path,
    *,
    create: bool,
) -> int:
    if not directory.is_absolute() or _NO_FOLLOW == 0 or _DIRECTORY == 0:
        raise AttemptLedgerError("ledger path cannot be opened safely")
    flags = os.O_RDONLY | _DIRECTORY | _NO_FOLLOW | _CLOSE_ON_EXEC
    descriptor = os.open(directory.anchor, flags)
    try:
        for component in directory.parts[1:]:
            if create:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            next_descriptor = os.open(
                component,
                flags,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
        ):
            raise AttemptLedgerError("ledger path is invalid")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _verify_bound_ledger_parent(binding: _BoundLedgerPath) -> None:
    visible_descriptor: int | None = None
    try:
        visible_descriptor = _open_directory_descriptor(
            binding.path.parent,
            create=False,
        )
        visible = os.fstat(visible_descriptor)
        current = os.fstat(binding.parent_descriptor)
    except (OSError, AttemptLedgerError) as exc:
        raise AttemptLedgerError("ledger path changed") from exc
    finally:
        if visible_descriptor is not None:
            os.close(visible_descriptor)
    if (
        (visible.st_dev, visible.st_ino) != binding.parent_identity
        or (current.st_dev, current.st_ino) != binding.parent_identity
    ):
        raise AttemptLedgerError("ledger path changed")


def _ledger_entry_exists(binding: _BoundLedgerPath) -> bool:
    try:
        os.stat(
            binding.name,
            dir_fd=binding.parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise AttemptLedgerError("canonical ledger is invalid") from exc
    return True


@contextmanager
def _bound_ledger_path(
    path: str | Path,
    *,
    create_parent: bool,
):
    canonical = _canonical_ledger_path(path)
    try:
        descriptor = _open_directory_descriptor(
            canonical.parent,
            create=create_parent,
        )
    except OSError as exc:
        raise AttemptLedgerError("ledger path is invalid") from exc
    metadata = os.fstat(descriptor)
    binding = _BoundLedgerPath(
        path=canonical,
        parent_descriptor=descriptor,
        parent_identity=(metadata.st_dev, metadata.st_ino),
    )
    try:
        _verify_bound_ledger_parent(binding)
        yield binding
        _verify_bound_ledger_parent(binding)
    finally:
        os.close(descriptor)


def _lock_anchor_path() -> Path:
    target = _LOCK_DIRECTORY.parent
    if not target.is_absolute():
        raise AttemptLedgerError(
            "canonical ledger lock is invalid"
        )
    current = Path(target.anchor)
    try:
        for component in target.parts[1:]:
            candidate = current / component
            metadata = os.lstat(candidate)
            if stat.S_ISLNK(metadata.st_mode):
                raise AttemptLedgerError(
                    "canonical ledger lock is invalid"
                )
            if metadata.st_uid == os.geteuid():
                return current
            current = candidate
    except OSError as exc:
        raise AttemptLedgerError(
            "canonical ledger lock is invalid"
        ) from exc
    return target


def _open_lock_root_descriptor() -> int:
    root = _lock_anchor_path()
    if _NO_FOLLOW == 0 or _DIRECTORY == 0:
        raise AttemptLedgerError(
            "canonical ledger lock is invalid"
        )
    flags = os.O_RDONLY | _DIRECTORY | _NO_FOLLOW | _CLOSE_ON_EXEC
    descriptor = os.open(root.anchor, flags)
    try:
        for component in root.parts[1:]:
            next_descriptor = os.open(
                component,
                flags,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise AttemptLedgerError(
                "canonical ledger lock is invalid"
            )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_lock_directory_descriptor(
    root_descriptor: int,
    *,
    create: bool,
) -> int:
    flags = os.O_RDONLY | _DIRECTORY | _NO_FOLLOW | _CLOSE_ON_EXEC
    anchor = _lock_anchor_path()
    try:
        relative_parts = _LOCK_DIRECTORY.relative_to(anchor).parts
    except ValueError as exc:
        raise AttemptLedgerError(
            "canonical ledger lock is invalid"
        ) from exc
    descriptor = os.dup(root_descriptor)
    try:
        for index, component in enumerate(relative_parts):
            is_lock_directory = index == len(relative_parts) - 1
            if create and is_lock_directory:
                try:
                    os.mkdir(
                        component,
                        mode=0o700,
                        dir_fd=descriptor,
                    )
                except FileExistsError:
                    pass
            next_descriptor = os.open(
                component,
                flags,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) & 0o077
        ):
            raise AttemptLedgerError(
                "canonical ledger lock is invalid"
            )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _lock_path(path: Path) -> Path:
    canonical = _canonical_ledger_path(path)
    identity = sha256(str(canonical).encode("utf-8")).hexdigest()
    return _LOCK_DIRECTORY / f"{identity}.lock"


def _verify_bound_lock_file(binding: _BoundLockFile) -> None:
    visible_root_descriptor: int | None = None
    visible_directory_descriptor: int | None = None
    try:
        visible_root_descriptor = _open_lock_root_descriptor()
        visible_root = os.fstat(visible_root_descriptor)
        current_root = os.fstat(binding.root_descriptor)
        visible_directory_descriptor = (
            _open_lock_directory_descriptor(
                binding.root_descriptor,
                create=False,
            )
        )
        visible_directory = os.fstat(visible_directory_descriptor)
        current_directory = os.fstat(binding.directory_descriptor)
        named_file = os.stat(
            binding.name,
            dir_fd=binding.directory_descriptor,
            follow_symlinks=False,
        )
        current_file = os.fstat(binding.file_descriptor)
    except (OSError, AttemptLedgerError) as exc:
        raise AttemptLedgerError(
            "canonical ledger lock changed"
        ) from exc
    finally:
        if visible_directory_descriptor is not None:
            os.close(visible_directory_descriptor)
        if visible_root_descriptor is not None:
            os.close(visible_root_descriptor)
    if (
        (visible_root.st_dev, visible_root.st_ino)
        != binding.root_identity
        or (current_root.st_dev, current_root.st_ino)
        != binding.root_identity
        or (visible_directory.st_dev, visible_directory.st_ino)
        != binding.directory_identity
        or (current_directory.st_dev, current_directory.st_ino)
        != binding.directory_identity
        or not stat.S_ISDIR(current_directory.st_mode)
        or current_directory.st_uid != os.geteuid()
        or stat.S_IMODE(current_directory.st_mode) & 0o077
        or (named_file.st_dev, named_file.st_ino)
        != binding.file_identity
        or (current_file.st_dev, current_file.st_ino)
        != binding.file_identity
        or not stat.S_ISREG(current_file.st_mode)
        or current_file.st_uid != os.geteuid()
        or current_file.st_nlink != 1
        or stat.S_IMODE(current_file.st_mode) & 0o077
    ):
        raise AttemptLedgerError("canonical ledger lock changed")


@contextmanager
def _bound_external_ledger_lock(
    path: Path,
    *,
    shared: bool,
):
    root_descriptor: int | None = None
    directory_descriptor: int | None = None
    file_descriptor: int | None = None
    root_locked = False
    file_locked = False
    mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    try:
        try:
            root_descriptor = _open_lock_root_descriptor()
            fcntl.flock(root_descriptor, mode)
            root_locked = True
            root_metadata = os.fstat(root_descriptor)
            directory_descriptor = _open_lock_directory_descriptor(
                root_descriptor,
                create=True,
            )
            directory_metadata = os.fstat(directory_descriptor)
            lock_path = _lock_path(path)
            file_descriptor = os.open(
                lock_path.name,
                os.O_RDWR | os.O_CREAT | _NO_FOLLOW | _CLOSE_ON_EXEC,
                0o600,
                dir_fd=directory_descriptor,
            )
            file_metadata = os.fstat(file_descriptor)
            named_file = os.stat(
                lock_path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(file_metadata.st_mode)
                or file_metadata.st_uid != os.geteuid()
                or file_metadata.st_nlink != 1
                or (file_metadata.st_dev, file_metadata.st_ino)
                != (named_file.st_dev, named_file.st_ino)
            ):
                raise AttemptLedgerError(
                    "canonical ledger lock is invalid"
                )
            os.fchmod(file_descriptor, 0o600)
            file_metadata = os.fstat(file_descriptor)
            fcntl.flock(file_descriptor, mode)
            file_locked = True
        except AttemptLedgerError:
            raise
        except OSError as exc:
            raise AttemptLedgerError(
                "canonical ledger lock is invalid"
            ) from exc
        binding = _BoundLockFile(
            root_descriptor=root_descriptor,
            root_identity=(
                root_metadata.st_dev,
                root_metadata.st_ino,
            ),
            directory_descriptor=directory_descriptor,
            directory_identity=(
                directory_metadata.st_dev,
                directory_metadata.st_ino,
            ),
            file_descriptor=file_descriptor,
            file_identity=(
                file_metadata.st_dev,
                file_metadata.st_ino,
            ),
            name=lock_path.name,
        )
        _verify_bound_lock_file(binding)
        yield
        _verify_bound_lock_file(binding)
    finally:
        if file_locked and file_descriptor is not None:
            fcntl.flock(file_descriptor, fcntl.LOCK_UN)
        if file_descriptor is not None:
            os.close(file_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        if root_locked and root_descriptor is not None:
            fcntl.flock(root_descriptor, fcntl.LOCK_UN)
        if root_descriptor is not None:
            os.close(root_descriptor)


@contextmanager
def _ledger_lock(path: Path, *, shared: bool = False):
    path = _canonical_ledger_path(path)
    with _bound_ledger_path(path, create_parent=True) as binding:
        with _bound_external_ledger_lock(path, shared=shared):
            _verify_bound_ledger_parent(binding)
            yield binding
            _verify_bound_ledger_parent(binding)


def _runtime_request_lock_path(context_path: str | Path) -> Path:
    canonical = Path(os.path.abspath(Path(context_path).expanduser()))
    identity = sha256(str(canonical).encode("utf-8")).hexdigest()
    return _RUNTIME_REQUEST_LOCK_DIRECTORY / f"{identity}.lock"


def _verify_runtime_request_lock(
    binding: _BoundLedgerPath,
    *,
    file_descriptor: int,
    file_identity: tuple[int, int],
) -> None:
    try:
        _verify_bound_ledger_parent(binding)
        named_file = os.stat(
            binding.name,
            dir_fd=binding.parent_descriptor,
            follow_symlinks=False,
        )
        current_file = os.fstat(file_descriptor)
    except (OSError, AttemptLedgerError) as exc:
        raise AttemptLedgerError(
            "runtime request lifecycle lock changed"
        ) from exc
    if (
        (named_file.st_dev, named_file.st_ino) != file_identity
        or (current_file.st_dev, current_file.st_ino) != file_identity
        or not stat.S_ISREG(current_file.st_mode)
        or current_file.st_uid != os.geteuid()
        or current_file.st_nlink != 1
        or stat.S_IMODE(current_file.st_mode) & 0o077
    ):
        raise AttemptLedgerError(
            "runtime request lifecycle lock changed"
        )


@contextmanager
def _runtime_request_lifecycle_lock(
    context_path: str | Path,
    *,
    shared: bool,
):
    lock_path = _runtime_request_lock_path(context_path)
    directory_descriptor: int | None = None
    file_descriptor: int | None = None
    file_locked = False
    try:
        try:
            directory_descriptor = _open_directory_descriptor(
                lock_path.parent,
                create=True,
            )
            directory_metadata = os.fstat(directory_descriptor)
            if (
                directory_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(directory_metadata.st_mode) & 0o077
            ):
                raise AttemptLedgerError(
                    "runtime request lifecycle lock is invalid"
                )
            file_descriptor = os.open(
                lock_path.name,
                os.O_RDWR | os.O_CREAT | _NO_FOLLOW | _CLOSE_ON_EXEC,
                0o600,
                dir_fd=directory_descriptor,
            )
            os.fchmod(file_descriptor, 0o600)
            file_metadata = os.fstat(file_descriptor)
            named_file = os.stat(
                lock_path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(file_metadata.st_mode)
                or file_metadata.st_uid != os.geteuid()
                or file_metadata.st_nlink != 1
                or (file_metadata.st_dev, file_metadata.st_ino)
                != (named_file.st_dev, named_file.st_ino)
            ):
                raise AttemptLedgerError(
                    "runtime request lifecycle lock is invalid"
                )
            binding = _BoundLedgerPath(
                path=lock_path,
                parent_descriptor=directory_descriptor,
                parent_identity=(
                    directory_metadata.st_dev,
                    directory_metadata.st_ino,
                ),
            )
            fcntl.flock(
                file_descriptor,
                fcntl.LOCK_SH if shared else fcntl.LOCK_EX,
            )
            file_locked = True
            file_identity = (
                file_metadata.st_dev,
                file_metadata.st_ino,
            )
        except AttemptLedgerError:
            raise
        except OSError as exc:
            raise AttemptLedgerError(
                "runtime request lifecycle lock is invalid"
            ) from exc
        _verify_runtime_request_lock(
            binding,
            file_descriptor=file_descriptor,
            file_identity=file_identity,
        )
        yield
        _verify_runtime_request_lock(
            binding,
            file_descriptor=file_descriptor,
            file_identity=file_identity,
        )
    finally:
        if file_locked and file_descriptor is not None:
            fcntl.flock(file_descriptor, fcntl.LOCK_UN)
        if file_descriptor is not None:
            os.close(file_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)


@contextmanager
def runtime_request_lifecycle_lease(context_path: str | Path):
    with _runtime_request_lifecycle_lock(
        context_path,
        shared=True,
    ):
        yield


def _validate_ledger(
    payload: object,
    *,
    expected_path: Path | None = None,
    allow_uncheckpointed: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AttemptLedgerError("canonical ledger is invalid")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise AttemptLedgerError("canonical ledger is invalid")
    revision = payload.get("revision")
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 0
    ):
        raise AttemptLedgerError("canonical ledger is invalid")
    if not isinstance(payload.get("attempts"), list):
        raise AttemptLedgerError("canonical ledger is invalid")
    if not isinstance(payload.get("authorizations"), list):
        raise AttemptLedgerError("canonical ledger is invalid")
    if payload.get("circuit_state") not in {"closed", "open"}:
        raise AttemptLedgerError("canonical ledger is invalid")
    ledger_path = payload.get("ledger_path")
    if not allow_uncheckpointed or ledger_path is not None:
        if (
            not isinstance(ledger_path, str)
            or not Path(ledger_path).is_absolute()
            or (
                expected_path is not None
                and ledger_path != str(_canonical_ledger_path(expected_path))
            )
        ):
            raise AttemptLedgerError("canonical ledger path mismatch")
    _verify_revision_chain(
        payload,
        allow_uncheckpointed=allow_uncheckpointed,
    )
    return payload


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AttemptLedgerError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise AttemptLedgerError(f"{label} is invalid")
    return payload


def _decode_json_object_bytes(
    content: bytes,
    *,
    label: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AttemptLedgerError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise AttemptLedgerError(f"{label} is invalid")
    return payload


def _read_regular_file_once(
    path: Path,
    *,
    label: str,
    binding: _BoundLedgerPath | None = None,
    allowed_link_counts: frozenset[int] = frozenset({1}),
) -> bytes:
    candidate = Path(os.path.abspath(path.expanduser()))
    if _NO_FOLLOW == 0:
        raise AttemptLedgerError(f"{label} cannot be read safely")
    if binding is None:
        with _bound_ledger_path(
            candidate,
            create_parent=False,
        ) as owned_binding:
            return _read_regular_file_once(
                candidate,
                label=label,
                binding=owned_binding,
                allowed_link_counts=allowed_link_counts,
            )
    assert binding is not None
    if binding.path != candidate:
        raise AttemptLedgerError(f"{label} path binding is invalid")
    flags = os.O_RDONLY | _NO_FOLLOW | _CLOSE_ON_EXEC
    descriptor: int | None = None
    try:
        _verify_bound_ledger_parent(binding)
        descriptor = os.open(
            binding.name,
            flags,
            dir_fd=binding.parent_descriptor,
        )
    except OSError as exc:
        raise AttemptLedgerError(f"{label} is invalid") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or opened.st_nlink not in allowed_link_counts
        ):
            raise AttemptLedgerError(f"{label} is invalid")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after_read = os.fstat(descriptor)
        named = os.stat(
            binding.name,
            dir_fd=binding.parent_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise AttemptLedgerError(f"{label} is invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if (
        not stat.S_ISREG(named.st_mode)
        or (opened.st_dev, opened.st_ino)
        != (after_read.st_dev, after_read.st_ino)
        or (opened.st_dev, opened.st_ino)
        != (named.st_dev, named.st_ino)
        or opened.st_size != after_read.st_size
        or opened.st_mtime_ns != after_read.st_mtime_ns
        or after_read.st_nlink not in allowed_link_counts
    ):
        raise AttemptLedgerError(f"{label} changed during read")
    _verify_bound_ledger_parent(binding)
    return b"".join(chunks)


def _sibling_binding(
    binding: _BoundLedgerPath,
    name: str,
) -> _BoundLedgerPath:
    return _BoundLedgerPath(
        path=binding.path.with_name(name),
        parent_descriptor=binding.parent_descriptor,
        parent_identity=binding.parent_identity,
    )


def _read_bound_file_if_present(
    binding: _BoundLedgerPath,
    *,
    label: str,
    allowed_link_counts: frozenset[int] = frozenset({1}),
) -> bytes | None:
    if not _ledger_entry_exists(binding):
        return None
    return _read_regular_file_once(
        binding.path,
        label=label,
        binding=binding,
        allowed_link_counts=allowed_link_counts,
    )


def _unlink_expected_bound_file(
    binding: _BoundLedgerPath,
    *,
    expected: bytes,
    label: str,
    allowed_link_counts: frozenset[int],
) -> None:
    content = _read_bound_file_if_present(
        binding,
        label=label,
        allowed_link_counts=allowed_link_counts,
    )
    if content is None:
        return
    if content != expected:
        raise AttemptLedgerError(f"{label} is invalid")
    try:
        os.unlink(
            binding.name,
            dir_fd=binding.parent_descriptor,
        )
    except OSError as exc:
        raise AttemptLedgerError(f"{label} is invalid") from exc
    _fsync_directory(binding.path.parent, binding=binding)


def _write_bound_immutable_json(
    *,
    binding: _BoundLedgerPath,
    payload: Mapping[str, object],
    label: str,
) -> None:
    data = _canonical_bytes(payload)
    temporary_binding = _sibling_binding(
        binding,
        f".{binding.name}.pending",
    )
    _verify_bound_ledger_parent(binding)
    current = _read_bound_file_if_present(
        binding,
        label=label,
        allowed_link_counts=frozenset({1, 2}),
    )
    if current == data:
        pending = _read_bound_file_if_present(
            temporary_binding,
            label=f"{label} temporary file",
            allowed_link_counts=frozenset({1, 2}),
        )
        if pending is not None:
            _unlink_expected_bound_file(
                temporary_binding,
                expected=data,
                label=f"{label} temporary file",
                allowed_link_counts=frozenset({1, 2}),
            )
        return
    if current is not None:
        if len(current) >= len(data) or not data.startswith(current):
            raise AttemptLedgerError(f"{label} is invalid")
        try:
            os.unlink(
                binding.name,
                dir_fd=binding.parent_descriptor,
            )
        except OSError as exc:
            raise AttemptLedgerError(f"{label} is invalid") from exc
        _fsync_directory(binding.path.parent, binding=binding)

    pending = _read_bound_file_if_present(
        temporary_binding,
        label=f"{label} temporary file",
    )
    if pending is not None and pending != data:
        if len(pending) >= len(data) or not data.startswith(pending):
            raise AttemptLedgerError(
                f"{label} temporary file is invalid"
            )
        try:
            os.unlink(
                temporary_binding.name,
                dir_fd=temporary_binding.parent_descriptor,
            )
        except OSError as exc:
            raise AttemptLedgerError(
                f"{label} temporary file is invalid"
            ) from exc
        _fsync_directory(
            temporary_binding.path.parent,
            binding=temporary_binding,
        )
        pending = None

    if pending is None:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary_binding.name,
                (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | _NO_FOLLOW
                    | _CLOSE_ON_EXEC
                ),
                0o600,
                dir_fd=temporary_binding.parent_descriptor,
            )
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or opened.st_nlink != 1
            ):
                raise AttemptLedgerError(
                    f"{label} temporary file is invalid"
                )
            with os.fdopen(descriptor, "wb") as output:
                descriptor = None
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
        except AttemptLedgerError:
            raise
        except OSError as exc:
            raise AttemptLedgerError(f"{label} is invalid") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        _fsync_directory(
            temporary_binding.path.parent,
            binding=temporary_binding,
        )

    _verify_bound_ledger_parent(binding)
    try:
        os.link(
            temporary_binding.name,
            binding.name,
            src_dir_fd=binding.parent_descriptor,
            dst_dir_fd=binding.parent_descriptor,
            follow_symlinks=False,
        )
    except FileExistsError:
        committed = _read_bound_file_if_present(
            binding,
            label=label,
            allowed_link_counts=frozenset({1, 2}),
        )
        if committed != data:
            raise AttemptLedgerError(f"{label} is invalid")
    except OSError as exc:
        raise AttemptLedgerError(f"{label} is invalid") from exc
    _fsync_directory(binding.path.parent, binding=binding)

    committed = _read_regular_file_once(
        binding.path,
        label=label,
        binding=binding,
        allowed_link_counts=frozenset({2}),
    )
    staged = _read_regular_file_once(
        temporary_binding.path,
        label=f"{label} temporary file",
        binding=temporary_binding,
        allowed_link_counts=frozenset({2}),
    )
    committed_stat = os.stat(
        binding.name,
        dir_fd=binding.parent_descriptor,
        follow_symlinks=False,
    )
    staged_stat = os.stat(
        temporary_binding.name,
        dir_fd=binding.parent_descriptor,
        follow_symlinks=False,
    )
    if (
        committed != data
        or staged != data
        or (committed_stat.st_dev, committed_stat.st_ino)
        != (staged_stat.st_dev, staged_stat.st_ino)
    ):
        raise AttemptLedgerError(f"{label} changed during commit")
    _unlink_expected_bound_file(
        temporary_binding,
        expected=data,
        label=f"{label} temporary file",
        allowed_link_counts=frozenset({2}),
    )
    if (
        _read_regular_file_once(
            binding.path,
            label=label,
            binding=binding,
        )
        != data
    ):
        raise AttemptLedgerError(f"{label} changed during commit")


def _read_attempt_context_once(
    path: Path,
) -> tuple[dict[str, Any], str]:
    content = _read_regular_file_once(path, label="attempt context")
    context = _decode_json_object_bytes(
        content,
        label="attempt context",
    )
    if _canonical_bytes(context) != content:
        raise AttemptLedgerError("attempt context content mismatch")
    return context, sha256(content).hexdigest()


def _recover_orphan_temp(
    path: Path,
    *,
    binding: _BoundLedgerPath,
) -> None:
    if binding.path != _canonical_ledger_path(path):
        raise AttemptLedgerError("ledger path binding is invalid")
    _verify_bound_ledger_parent(binding)
    legacy_name = ledger_temp_path(path).name
    unique_prefix = _ledger_temp_prefix(path)
    temporary_paths = tuple(
        name
        for name in os.listdir(binding.parent_descriptor)
        if (
            name == legacy_name
            or name.startswith(unique_prefix)
        )
    )
    if not temporary_paths:
        return
    try:
        metadata = os.stat(
            binding.name,
            dir_fd=binding.parent_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise AttemptLedgerError("canonical ledger is invalid") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise AttemptLedgerError("canonical ledger is invalid")
    _validate_ledger(
        _decode_json_object_bytes(
            _read_regular_file_once(
                path,
                label="canonical ledger",
                binding=binding,
            ),
            label="canonical ledger",
        ),
        expected_path=path,
    )
    for temporary_name in temporary_paths:
        try:
            metadata = os.stat(
                temporary_name,
                dir_fd=binding.parent_descriptor,
                follow_symlinks=False,
            )
            if not (
                stat.S_ISREG(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
            ):
                raise AttemptLedgerError(
                    "orphan ledger temporary file is invalid"
                )
            os.unlink(
                temporary_name,
                dir_fd=binding.parent_descriptor,
            )
        except (IsADirectoryError, PermissionError, OSError) as exc:
            raise AttemptLedgerError(
                "orphan ledger temporary file is invalid"
            ) from exc
    os.fsync(binding.parent_descriptor)
    _verify_bound_ledger_parent(binding)


def _read_ledger_unlocked(
    path: Path,
    *,
    binding: _BoundLedgerPath,
) -> dict[str, Any]:
    canonical = _canonical_ledger_path(path)
    content = _read_regular_file_once(
        canonical,
        label="canonical ledger",
        binding=binding,
    )
    payload = _validate_ledger(
        _decode_json_object_bytes(content, label="canonical ledger"),
        expected_path=canonical,
    )
    _verify_terminal_evidence_manifests(payload)
    _verify_failure_reclassifications(payload)
    return payload


def _verify_terminal_evidence_manifests(
    payload: dict[str, Any],
) -> None:
    for attempt in payload["attempts"]:
        if not isinstance(attempt, dict):
            continue
        manifest = attempt.get("terminal_evidence")
        if manifest is None:
            if (
                attempt.get("result") == "passed"
                and isinstance(attempt.get("context_path"), str)
                and attempt["context_path"] not in {
                    "",
                    "historical-unavailable",
                }
            ):
                raise AttemptLedgerError("terminal evidence changed")
            continue
        if (
            attempt.get("result") not in _TERMINAL_RESULTS
            or not isinstance(manifest, dict)
        ):
            raise AttemptLedgerError("terminal evidence changed")
        context_path = Path(str(attempt.get("context_path")))
        try:
            context, context_sha256 = _read_attempt_context_once(
                context_path
            )
        except AttemptLedgerError as exc:
            raise AttemptLedgerError(
                "terminal evidence changed"
            ) from exc
        if context_sha256 != attempt.get("context_sha256"):
            raise AttemptLedgerError("terminal evidence changed")
        _require_recorded_terminal_evidence_manifest(
            manifest,
            output_directory=context.get("output_directory"),
            allowed_additional_subdirectories=(
                ("real-backend",)
                if attempt.get("trajectory_set") == "translation"
                else ()
            ),
        )


def _verify_failure_reclassifications(
    payload: dict[str, Any],
) -> None:
    for attempt in payload["attempts"]:
        if not isinstance(attempt, dict):
            continue
        history = attempt.get("failure_reclassifications")
        if history is None:
            continue
        if not isinstance(history, list) or not history:
            raise AttemptLedgerError(
                "failure reclassification history is invalid"
            )
        if not isinstance(history[0], dict):
            raise AttemptLedgerError(
                "failure reclassification history is invalid"
            )
        evidence_directory = Path(
            str(attempt.get("evidence_directory"))
        ).resolve()
        context_path = Path(str(attempt.get("context_path")))
        if (
            not context_path.is_file()
            or attempt.get("context_sha256")
            != _file_sha256(context_path)
        ):
            raise AttemptLedgerError(
                "failure reclassification context mismatch"
            )
        context = _load_json_object(
            context_path,
            label="attempt context",
        )
        readiness_path = Path(str(context.get("readiness_path")))
        if (
            not readiness_path.is_file()
            or context.get("readiness_sha256")
            != _file_sha256(readiness_path)
        ):
            raise AttemptLedgerError(
                "failure reclassification readiness mismatch"
            )
        readiness = _load_json_object(
            readiness_path,
            label="readiness",
        )
        attempt_record_sha256 = _attempt_allocation_sha256(attempt)
        current_evidence_hashes = {
            name: _file_sha256(evidence_directory / name)
            for name in _FAILURE_EVIDENCE_FILES
            if (evidence_directory / name).is_file()
        }
        if set(current_evidence_hashes) != _FAILURE_EVIDENCE_FILES:
            if history[0].get(
                "failure_code"
            ) not in _INDEXED_RUNTIME_FAILURE_CODES:
                raise AttemptLedgerError(
                    "failure reclassification evidence mismatch"
                )
            (
                current_evidence_hashes,
                evidence_bundle_sha256,
            ) = _recorded_failure_evidence_binding(
                attempt,
                evidence_directory=evidence_directory,
            )
        else:
            evidence_bundle_sha256 = _failure_evidence_sha256(
                evidence_directory
            )
        expected_owner = history[0].get("previous_failure_owner")
        expected_code = history[0].get("previous_failure_code")
        for item in history:
            if (
                not isinstance(item, dict)
                or item.get("previous_failure_owner") != expected_owner
                or item.get("previous_failure_code") != expected_code
            ):
                raise AttemptLedgerError(
                    "failure reclassification history is invalid"
                )
            audit_path = Path(
                str(item.get("independent_audit_path"))
            )
            audit = (
                _load_json_object(
                    audit_path,
                    label="failure reclassification audit",
                )
                if audit_path.is_file()
                else None
            )
            repair_files = (
                audit.get("repair_evidence_files")
                if audit is not None
                else None
            )
            repair_hashes = (
                audit.get("repair_evidence_sha256")
                if audit is not None
                else None
            )
            current_repair_hashes = (
                {
                    name: _file_sha256(Path(str(path)))
                    for name, path in repair_files.items()
                    if (
                        name in _RECLASSIFICATION_REPAIR_EVIDENCE_KEYS
                        and Path(str(path)).is_file()
                    )
                }
                if isinstance(repair_files, dict)
                else {}
            )
            if (
                audit is None
                or item.get("independent_audit_sha256")
                != _file_sha256(audit_path)
                or audit.get("schema_version")
                != "guide-smoke-failure-reclassification-v1"
                or audit.get("passed") is not True
                or audit.get("plan_revision")
                != attempt.get("plan_revision")
                or audit.get("attempt_id")
                != attempt.get("attempt_id")
                or audit.get("evidence_directory")
                != str(evidence_directory)
                or audit.get("previous_failure_owner")
                != item.get("previous_failure_owner")
                or audit.get("previous_failure_code")
                != item.get("previous_failure_code")
                or audit.get("first_failure_owner")
                != item.get("first_failure_owner")
                or audit.get("failure_code")
                != item.get("failure_code")
                or _RECLASSIFICATION_OWNER_BY_CODE.get(
                    item.get("failure_code")
                )
                != item.get("first_failure_owner")
                or item.get("first_failure_turn_id")
                != attempt.get("first_failure_turn_id")
                or audit.get("first_failure_turn_id")
                != item.get("first_failure_turn_id")
                or item.get("code_revision")
                != attempt.get("code_revision")
                or audit.get("code_revision")
                != item.get("code_revision")
                or item.get("attempt_context_sha256")
                != attempt.get("context_sha256")
                or audit.get("attempt_context_sha256")
                != item.get("attempt_context_sha256")
                or item.get("attempt_record_sha256")
                != attempt_record_sha256
                or audit.get("attempt_record_sha256")
                != item.get("attempt_record_sha256")
                or context.get("attempt_record_sha256")
                != item.get("attempt_record_sha256")
                or item.get("readiness_path")
                != str(readiness_path.resolve())
                or audit.get("readiness_path")
                != item.get("readiness_path")
                or item.get("readiness_sha256")
                != context.get("readiness_sha256")
                or audit.get("readiness_sha256")
                != item.get("readiness_sha256")
                or item.get("protected_payload_sha256")
                != readiness.get("protected_payload_sha256")
                or audit.get("protected_payload_sha256")
                != item.get("protected_payload_sha256")
                or audit.get("pre_reclassification_ledger_revision")
                != item.get("pre_reclassification_ledger_revision")
                or not isinstance(
                    item.get("pre_reclassification_ledger_revision"),
                    int,
                )
                or isinstance(
                    item.get("pre_reclassification_ledger_revision"),
                    bool,
                )
                or item["pre_reclassification_ledger_revision"]
                >= payload["revision"]
                or audit.get("reviewed_evidence_sha256")
                != item.get("reviewed_evidence_sha256")
                or item.get("reviewed_evidence_sha256")
                != current_evidence_hashes
                or audit.get("evidence_bundle_sha256")
                != item.get("evidence_bundle_sha256")
                or item.get("evidence_bundle_sha256")
                != evidence_bundle_sha256
                or not isinstance(repair_files, dict)
                or set(repair_files)
                != _RECLASSIFICATION_REPAIR_EVIDENCE_KEYS
                or not isinstance(repair_hashes, dict)
                or set(repair_hashes)
                != _RECLASSIFICATION_REPAIR_EVIDENCE_KEYS
                or item.get("repair_evidence_files")
                != repair_files
                or item.get("repair_evidence_sha256")
                != repair_hashes
                or current_repair_hashes != repair_hashes
                or not isinstance(audit.get("conclusion"), str)
                or not audit["conclusion"]
            ):
                raise AttemptLedgerError(
                    "failure reclassification evidence mismatch"
                )
            expected_owner = item.get("first_failure_owner")
            expected_code = item.get("failure_code")
        if (
            attempt.get("first_failure_owner") != expected_owner
            or attempt.get("failure_code") != expected_code
        ):
            raise AttemptLedgerError(
                "failure reclassification history is invalid"
            )


def _fsync_directory(
    path: Path,
    *,
    binding: _BoundLedgerPath | None = None,
) -> None:
    if binding is not None:
        if binding.path.parent != Path(os.path.abspath(path)):
            raise AttemptLedgerError("ledger path binding is invalid")
        _verify_bound_ledger_parent(binding)
        os.fsync(binding.parent_descriptor)
        return
    descriptor = _open_directory_descriptor(
        Path(os.path.abspath(path)),
        create=False,
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_ledger(
    path: Path,
    payload: dict[str, Any],
    *,
    binding: _BoundLedgerPath | None = None,
) -> None:
    path = _canonical_ledger_path(path)
    if binding is None:
        with _bound_ledger_path(
            path,
            create_parent=False,
        ) as owned_binding:
            _atomic_write_ledger(
                path,
                payload,
                binding=owned_binding,
            )
        return
    if binding.path != path:
        raise AttemptLedgerError("ledger path binding is invalid")
    _validate_ledger(payload, expected_path=path)
    data = _canonical_bytes(payload)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor: int | None = None
    temporary_name: str | None = None
    for _ in range(8):
        candidate_name = _new_ledger_temp_path(path).name
        try:
            descriptor = os.open(
                candidate_name,
                flags,
                0o600,
                dir_fd=binding.parent_descriptor,
            )
        except FileExistsError:
            continue
        temporary_name = candidate_name
        break
    if descriptor is None or temporary_name is None:
        raise AttemptLedgerError(
            "could not allocate ledger temporary file"
        )
    output = os.fdopen(descriptor, "wb")
    descriptor = None
    with output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    _verify_bound_ledger_parent(binding)
    try:
        os.replace(
            temporary_name,
            binding.name,
            src_dir_fd=binding.parent_descriptor,
            dst_dir_fd=binding.parent_descriptor,
        )
    except OSError:
        _verify_bound_ledger_parent(binding)
        raise
    _fsync_directory(path.parent, binding=binding)
    _verify_bound_ledger_parent(binding)


def _write_initial_ledger(
    path: Path,
    payload: dict[str, Any],
    *,
    binding: _BoundLedgerPath | None = None,
) -> None:
    path = _canonical_ledger_path(path)
    if binding is None:
        with _bound_ledger_path(
            path,
            create_parent=True,
        ) as owned_binding:
            _write_initial_ledger(
                path,
                payload,
                binding=owned_binding,
            )
        return
    if binding.path != path:
        raise AttemptLedgerError("ledger path binding is invalid")
    _validate_ledger(payload, expected_path=path)
    temporary_name = f".{path.name}.init-{uuid4().hex}"
    try:
        descriptor = os.open(
            temporary_name,
            (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | _NO_FOLLOW
                | _CLOSE_ON_EXEC
            ),
            0o600,
            dir_fd=binding.parent_descriptor,
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(_canonical_bytes(payload))
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(
                temporary_name,
                binding.name,
                src_dir_fd=binding.parent_descriptor,
                dst_dir_fd=binding.parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise AttemptLedgerError(
                "canonical ledger already exists"
            ) from exc
        _fsync_directory(path.parent, binding=binding)
        _verify_bound_ledger_parent(binding)
    finally:
        try:
            os.unlink(
                temporary_name,
                dir_fd=binding.parent_descriptor,
            )
        except FileNotFoundError:
            pass


def _write_immutable_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as output:
            output.write(_canonical_bytes(payload))
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as exc:
        raise AttemptLedgerError(
            "attempt context path already exists"
        ) from exc
    _fsync_directory(path.parent)


def _rollback_attempt_allocation(
    *,
    binding: _BoundLedgerPath,
    attempt_id: str,
    context: Mapping[str, object],
    output_directory: Path,
    context_path: Path,
) -> None:
    _remove_attempt_context_witness(
        binding=binding,
        attempt_id=attempt_id,
        context=context,
    )
    try:
        context_stat = context_path.lstat()
    except FileNotFoundError:
        context_stat = None
    if context_stat is not None:
        if (
            stat.S_ISLNK(context_stat.st_mode)
            or not stat.S_ISREG(context_stat.st_mode)
        ):
            raise AttemptLedgerError(
                "attempt allocation rollback is unsafe"
            )
        context_path.unlink()
    try:
        output_directory.rmdir()
    except OSError as exc:
        raise AttemptLedgerError(
            "attempt allocation rollback failed"
        ) from exc
    _fsync_directory(output_directory.parent)


def _failure_counts(
    payload: dict[str, Any],
    *,
    plan_revision: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for attempt in payload["attempts"]:
        if (
            not isinstance(attempt, dict)
            or attempt.get("plan_revision") != plan_revision
            or attempt.get("result") != "failed"
        ):
            continue
        owners = {
            owner
            for owner in (
                attempt.get("first_failure_owner"),
                *(
                    item.get("previous_failure_owner")
                    for item in attempt.get(
                        "failure_reclassifications",
                        (),
                    )
                    if isinstance(item, dict)
                ),
            )
            if isinstance(owner, str) and owner
        }
        for owner in owners:
            counts[owner] = counts.get(owner, 0) + 1
    return counts


def _circuit_state(payload: dict[str, Any]) -> str:
    plan_revisions = {
        attempt.get("plan_revision")
        for attempt in payload["attempts"]
        if isinstance(attempt, dict)
        and isinstance(attempt.get("plan_revision"), str)
    }
    return (
        "open"
        if any(
            count >= 2
            for revision in plan_revisions
            for count in _failure_counts(
                payload,
                plan_revision=revision,
            ).values()
        )
        else "closed"
    )


def initialize_ledger(
    path: str | Path,
    *,
    attempts: Sequence[dict[str, object]] = (),
) -> dict[str, Any]:
    ledger = _canonical_ledger_path(path)
    with _ledger_lock(ledger) as binding:
        _recover_orphan_temp(ledger, binding=binding)
        if _ledger_entry_exists(binding):
            raise AttemptLedgerError("canonical ledger already exists")
        payload: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "ledger_path": str(ledger),
            "revision": 0,
            "circuit_state": "closed",
            "attempts": [deepcopy(item) for item in attempts],
            "authorizations": [],
            "revision_chain": [],
        }
        payload["circuit_state"] = _circuit_state(payload)
        _append_revision(payload, operation="initialized")
        _write_initial_ledger(ledger, payload, binding=binding)
        return deepcopy(payload)


def migrate_legacy_ledger(
    *,
    source_path: str | Path,
    target_path: str | Path,
    expected_source_sha256: str,
) -> dict[str, Any]:
    source = _canonical_ledger_path(source_path)
    target = _canonical_ledger_path(target_path)
    if not _is_sha256(expected_source_sha256):
        raise AttemptLedgerError("legacy ledger source hash is invalid")
    try:
        source_bytes = _read_regular_file_once(
            source,
            label="legacy ledger source",
        )
        payload = json.loads(source_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise AttemptLedgerError("legacy ledger source is invalid") from exc
    if sha256(source_bytes).hexdigest() != expected_source_sha256:
        raise AttemptLedgerError("legacy ledger source hash mismatch")
    if not isinstance(payload, dict):
        raise AttemptLedgerError("legacy ledger source is invalid")
    if (
        "revision_chain" in payload
        or payload.get("schema_version") != _SCHEMA_VERSION
        or not isinstance(payload.get("revision"), int)
        or isinstance(payload.get("revision"), bool)
        or payload["revision"] < 0
        or not isinstance(payload.get("attempts"), list)
        or not isinstance(payload.get("authorizations"), list)
        or payload.get("circuit_state") not in {"closed", "open"}
    ):
        raise AttemptLedgerError("legacy ledger source is invalid")
    _verify_failure_reclassifications(payload)
    migrated = deepcopy(payload)
    migrated["ledger_path"] = str(target)
    migrated["revision_chain"] = []
    _append_revision(
        migrated,
        operation="legacy_checkpoint",
        source_sha256=expected_source_sha256,
    )
    with _ledger_lock(target) as binding:
        if _ledger_entry_exists(binding):
            raise AttemptLedgerError("canonical ledger already exists")
        _write_initial_ledger(target, migrated, binding=binding)
    return deepcopy(migrated)


def _manifest_repository_root(
    root_value: object,
    *,
    error_message: str,
) -> Path:
    if not isinstance(root_value, str) or not root_value:
        raise AttemptLedgerError(error_message)
    root = Path(root_value)
    runtime_root = _REPO_ROOT.resolve()
    if (
        not root.is_absolute()
        or str(root.resolve()) != root_value
        or root.resolve() != runtime_root
    ):
        raise AttemptLedgerError(error_message)
    try:
        git_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise AttemptLedgerError(error_message) from exc
    if (
        git_root.returncode != 0
        or not git_root.stdout.strip()
        or Path(git_root.stdout.strip()).resolve() != runtime_root
    ):
        raise AttemptLedgerError(error_message)
    return runtime_root


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
    return path.resolve() == epoch_root / (
        f"task11-candidate-manifest-{revision_match.group(1)}.json"
    )


def _candidate_readiness_path(manifest_path: Path) -> Path:
    match = re.fullmatch(
        r"task11-candidate-manifest(?P<suffix>-r\d+)?\.json",
        manifest_path.name,
    )
    if match is None:
        raise AttemptLedgerError(
            "checkpoint candidate manifest authority is invalid"
        )
    return manifest_path.with_name(
        "task11-candidate-readiness"
        f"{match.group('suffix') or ''}.json"
    )


def _checkpoint_manifest_authority(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    ledger_path: Path,
    reject_existing_readiness: bool = True,
) -> tuple[dict[str, Any], int, Path]:
    manifest_file = Path(manifest_path)
    manifest_bytes = _read_regular_file_once(
        manifest_file,
        label="checkpoint candidate manifest",
    )
    if (
        not _is_sha256(expected_manifest_sha256)
        or sha256(manifest_bytes).hexdigest()
        != expected_manifest_sha256
    ):
        raise AttemptLedgerError(
            "checkpoint candidate manifest digest is invalid"
        )
    manifest = _decode_json_object_bytes(
        manifest_bytes,
        label="checkpoint candidate manifest",
    )
    repair_epoch = manifest.get("repair_epoch")
    mutable = manifest.get("mutable_evidence_paths")
    authority = manifest.get("pre_checkpoint_ledger")
    if (
        manifest.get("schema_version")
        != "guide-task11-candidate-manifest-v1"
        or not isinstance(repair_epoch, int)
        or isinstance(repair_epoch, bool)
        or repair_epoch < 1
        or not isinstance(mutable, list)
        or len(mutable) != 1
        or not isinstance(mutable[0], str)
        or not isinstance(authority, dict)
        or set(authority)
        != {"path", "sha256", "revision", "revision_hash"}
        or not _is_sha256(authority.get("sha256"))
        or not isinstance(authority.get("revision"), int)
        or isinstance(authority.get("revision"), bool)
        or authority["revision"] < 0
        or not _is_sha256(authority.get("revision_hash"))
    ):
        raise AttemptLedgerError(
            "checkpoint candidate manifest authority is invalid"
        )
    root = _manifest_repository_root(
        manifest.get("repository_root"),
        error_message="checkpoint candidate manifest authority is invalid",
    )
    expected_ledger = _canonical_ledger_path(
        root / _CANONICAL_LEDGER_RELATIVE_PATH
    )
    readiness_path = _candidate_readiness_path(
        manifest_file.resolve()
    )
    if (
        mutable != [_CANONICAL_LEDGER_RELATIVE_PATH]
        or not _candidate_manifest_path_is_valid(
            root=root,
            path=manifest_file,
            repair_epoch=repair_epoch,
            plan_revision=manifest.get("plan_revision"),
        )
        or ledger_path != expected_ledger
        or authority.get("path") != str(expected_ledger)
    ):
        raise AttemptLedgerError(
            "checkpoint candidate manifest authority is invalid"
        )
    if (
        reject_existing_readiness
        and (
            readiness_path.exists()
            or readiness_path.is_symlink()
        )
    ):
        raise AttemptLedgerError(
            "checkpoint rejected because candidate readiness already exists"
        )
    return dict(authority), repair_epoch, readiness_path


def _checkpoint_authority_binding(
    binding: _BoundLedgerPath,
) -> _BoundLedgerPath:
    return _BoundLedgerPath(
        path=binding.path.with_name(_CHECKPOINT_AUTHORITY_FILENAME),
        parent_descriptor=binding.parent_descriptor,
        parent_identity=binding.parent_identity,
    )


def _write_checkpoint_authority(
    binding: _BoundLedgerPath,
    payload: Mapping[str, object],
) -> None:
    authority_binding = _checkpoint_authority_binding(binding)
    _write_bound_immutable_json(
        binding=authority_binding,
        payload=payload,
        label="checkpoint authority",
    )


def _read_checkpoint_authority(
    binding: _BoundLedgerPath,
) -> dict[str, Any] | None:
    authority_binding = _checkpoint_authority_binding(binding)
    if not _ledger_entry_exists(authority_binding):
        return None
    content = _read_regular_file_once(
        authority_binding.path,
        label="checkpoint authority",
        binding=authority_binding,
    )
    payload = _decode_json_object_bytes(
        content,
        label="checkpoint authority",
    )
    if _canonical_bytes(payload) != content:
        raise AttemptLedgerError(
            "checkpoint authority content mismatch"
        )
    return payload


def _checkpoint_authority_payload(
    *,
    ledger: Path,
    source_authority: Mapping[str, object],
    checkpoint: Mapping[str, object],
    manifest_sha256: str,
    repair_epoch: int,
    readiness_path: Path,
) -> dict[str, object]:
    return {
        "schema_version": _CHECKPOINT_AUTHORITY_SCHEMA,
        "ledger_path": str(ledger),
        "source_sha256": source_authority["sha256"],
        "source_revision": source_authority["revision"],
        "source_revision_hash": source_authority["revision_hash"],
        "checkpoint_revision": checkpoint["revision"],
        "checkpoint_revision_hash": checkpoint["revision_hash"],
        "checkpoint_state_sha256": checkpoint["state_sha256"],
        "origin_manifest_sha256": manifest_sha256,
        "origin_repair_epoch": repair_epoch,
        "origin_readiness_path": str(readiness_path.resolve()),
    }


def _validate_checkpoint_authority(
    payload: object,
    *,
    expected: Mapping[str, object],
    root: Path,
) -> Path:
    if not isinstance(payload, dict) or set(payload) != set(expected):
        raise AttemptLedgerError("checkpoint authority is invalid")
    for key in (
        "schema_version",
        "ledger_path",
        "source_sha256",
        "source_revision",
        "source_revision_hash",
        "checkpoint_revision",
        "checkpoint_revision_hash",
        "checkpoint_state_sha256",
    ):
        if payload.get(key) != expected.get(key):
            raise AttemptLedgerError(
                "checkpoint authority does not match ledger"
            )
    origin_epoch = payload.get("origin_repair_epoch")
    origin_manifest_sha256 = payload.get("origin_manifest_sha256")
    origin_readiness = payload.get("origin_readiness_path")
    if (
        not isinstance(origin_epoch, int)
        or isinstance(origin_epoch, bool)
        or origin_epoch < 1
        or not _is_sha256(origin_manifest_sha256)
        or not isinstance(origin_readiness, str)
    ):
        raise AttemptLedgerError("checkpoint authority is invalid")
    origin_directory = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / f"repair-epoch-{origin_epoch}"
    )
    origin_manifest = (
        origin_directory / "task11-candidate-manifest.json"
    )
    expected_readiness = (
        origin_directory / "task11-candidate-readiness.json"
    )
    try:
        origin_manifest_bytes = _read_regular_file_once(
            origin_manifest,
            label="checkpoint origin manifest",
        )
    except AttemptLedgerError as exc:
        raise AttemptLedgerError(
            "checkpoint authority is invalid"
        ) from exc
    if (
        origin_readiness != str(expected_readiness.resolve())
        or sha256(origin_manifest_bytes).hexdigest()
        != origin_manifest_sha256
    ):
        raise AttemptLedgerError("checkpoint authority is invalid")
    return expected_readiness


def _verify_published_readiness_anchors(
    *,
    root: Path,
    ledger: Path,
    payload: Mapping[str, object],
) -> None:
    evidence_root = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
    )
    paths = (
        evidence_root / "task11-candidate-readiness.json",
        *sorted(
            evidence_root.glob(
                "repair-epoch-*/task11-candidate-readiness.json"
            )
        ),
        *sorted(
            evidence_root.glob(
                "repair-epoch-*/task11-candidate-readiness-r*.json"
            )
        ),
    )
    chain = payload.get("revision_chain")
    if not isinstance(chain, list):
        raise AttemptLedgerError("canonical ledger is invalid")
    for readiness_path in paths:
        if not readiness_path.exists() and not readiness_path.is_symlink():
            continue
        readiness = _decode_json_object_bytes(
            _read_regular_file_once(
                readiness_path,
                label="published candidate readiness",
            ),
            label="published candidate readiness",
        )
        readiness_ledger = readiness.get("ledger_path")
        if (
            readiness_ledger is not None
            and readiness_ledger != str(ledger)
        ):
            continue
        anchor_revision = readiness.get("ledger_anchor_revision")
        anchor_hash = readiness.get("ledger_anchor_hash")
        if (
            not isinstance(anchor_revision, int)
            or isinstance(anchor_revision, bool)
            or anchor_revision < 0
            or not _is_sha256(anchor_hash)
        ):
            raise AttemptLedgerError(
                "published readiness ledger anchor is invalid"
            )
        matches = [
            entry
            for entry in chain
            if (
                isinstance(entry, dict)
                and entry.get("revision") == anchor_revision
                and entry.get("revision_hash") == anchor_hash
            )
        ]
        if len(matches) != 1:
            raise AttemptLedgerError(
                "checkpoint rollback detected"
            )


def checkpoint_ledger(
    *,
    ledger_path: str | Path,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    ledger = _canonical_ledger_path(ledger_path)
    authority, repair_epoch, readiness_path = (
        _checkpoint_manifest_authority(
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        ledger_path=ledger,
        )
    )
    expected_source_sha256 = str(authority["sha256"])
    with _ledger_lock(ledger) as binding:
        source_bytes = _read_regular_file_once(
            ledger,
            label="ledger checkpoint source",
            binding=binding,
        )
        if sha256(source_bytes).hexdigest() != expected_source_sha256:
            raise AttemptLedgerError(
                "reviewed ledger checkpoint source mismatch"
            )
        payload = _decode_json_object_bytes(
            source_bytes,
            label="ledger checkpoint source",
        )
        _validate_ledger(
            payload,
            expected_path=ledger,
            allow_uncheckpointed=True,
        )
        _verify_published_readiness_anchors(
            root=_REPO_ROOT.resolve(),
            ledger=ledger,
            payload=payload,
        )
        source_tip = payload["revision_chain"][-1]
        if (
            payload.get("revision") != authority["revision"]
            or source_tip.get("revision")
            != authority["revision"]
            or source_tip.get("revision_hash")
            != authority["revision_hash"]
        ):
            raise AttemptLedgerError(
                "reviewed ledger checkpoint source mismatch"
            )
        if any(
            isinstance(entry, dict) and "state_snapshot" in entry
            for entry in payload["revision_chain"]
        ):
            raise AttemptLedgerError(
                "ledger already has a state checkpoint"
            )
        original_chain = deepcopy(payload["revision_chain"])
        checkpointed = deepcopy(payload)
        checkpointed["ledger_path"] = str(ledger)
        checkpointed["revision"] += 1
        checkpointed["circuit_state"] = _circuit_state(checkpointed)
        checkpoint = _append_revision(
            checkpointed,
            operation="state_checkpoint",
            source_sha256=expected_source_sha256,
        )
        if checkpointed["revision_chain"][:-1] != original_chain:
            raise AttemptLedgerError(
                "ledger checkpoint rewrote revision history"
            )
        checkpoint_authority = _checkpoint_authority_payload(
            ledger=ledger,
            source_authority=authority,
            checkpoint=checkpoint,
            manifest_sha256=expected_manifest_sha256,
            repair_epoch=repair_epoch,
            readiness_path=readiness_path,
        )
        _write_checkpoint_authority(
            binding,
            checkpoint_authority,
        )
        existing_authority = _read_checkpoint_authority(binding)
        if existing_authority is not None:
            origin_readiness = _validate_checkpoint_authority(
                existing_authority,
                expected=checkpoint_authority,
                root=_REPO_ROOT.resolve(),
            )
            if (
                origin_readiness.exists()
                or origin_readiness.is_symlink()
            ):
                raise AttemptLedgerError(
                    "checkpoint rollback detected"
                )
        authorization_ids: set[str] = set()
        for authorization in checkpointed["authorizations"]:
            if not isinstance(authorization, dict):
                raise AttemptLedgerError("canonical ledger is invalid")
            authorization_id = authorization.get("authorization_id")
            if not isinstance(authorization_id, str):
                raise AttemptLedgerError("canonical ledger is invalid")
            authorization_ids.add(authorization_id)
            _write_authorization_receipt(
                binding=binding,
                payload=_authorization_receipt_payload(
                    ledger=ledger,
                    authorization=authorization,
                    revision=_authorization_revision(
                        checkpointed,
                        authorization_id=authorization_id,
                    ),
                ),
            )
        if _verify_authorization_receipts(
            binding=binding,
            payload=checkpointed,
        ) != authorization_ids:
            raise AttemptLedgerError(
                "authorization receipt backfill is incomplete"
            )
        _atomic_write_ledger(
            ledger,
            checkpointed,
            binding=binding,
        )
        return deepcopy(checkpointed)


def verify_ledger_checkpoint_authority(
    *,
    ledger_path: str | Path,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    ledger = _canonical_ledger_path(ledger_path)
    authority, repair_epoch, readiness_path = (
        _checkpoint_manifest_authority(
            manifest_path=manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
            ledger_path=ledger,
            reject_existing_readiness=False,
        )
    )
    with _ledger_lock(ledger) as binding:
        payload = _read_ledger_unlocked(ledger, binding=binding)
        chain = payload["revision_chain"]
        matches = [
            (index, entry)
            for index, entry in enumerate(chain)
            if (
                isinstance(entry, dict)
                and entry.get("revision") == authority["revision"]
                and entry.get("revision_hash")
                == authority["revision_hash"]
            )
        ]
        if len(matches) != 1:
            raise AttemptLedgerError(
                "checkpoint authority does not match ledger"
            )
        index, source_entry = matches[0]
        if index + 1 >= len(chain):
            raise AttemptLedgerError(
                "checkpoint authority does not match ledger"
            )
        checkpoint = chain[index + 1]
        if (
            not isinstance(checkpoint, dict)
            or checkpoint.get("operation") != "state_checkpoint"
            or checkpoint.get("previous_hash")
            != source_entry["revision_hash"]
            or checkpoint.get("source_sha256")
            != authority["sha256"]
            or "state_snapshot" not in checkpoint
        ):
            raise AttemptLedgerError(
                "checkpoint authority does not match ledger"
            )
        expected = _checkpoint_authority_payload(
            ledger=ledger,
            source_authority=authority,
            checkpoint=checkpoint,
            manifest_sha256=expected_manifest_sha256,
            repair_epoch=repair_epoch,
            readiness_path=readiness_path,
        )
        stored = _read_checkpoint_authority(binding)
        if stored is None:
            raise AttemptLedgerError(
                "checkpoint authority is missing"
            )
        _validate_checkpoint_authority(
            stored,
            expected=expected,
            root=_REPO_ROOT.resolve(),
        )
        return deepcopy(stored)


def _authorization_receipt_name(authorization_id: str) -> str:
    if not re.fullmatch(r"auth_[0-9a-f]{32}", authorization_id):
        raise AttemptLedgerError("authorization identity is invalid")
    return (
        f"{_AUTHORIZATION_RECEIPT_PREFIX}"
        f"{authorization_id}.json"
    )


def _authorization_receipt_binding(
    binding: _BoundLedgerPath,
    authorization_id: str,
) -> _BoundLedgerPath:
    return _sibling_binding(
        binding,
        _authorization_receipt_name(authorization_id),
    )


def _attempt_context_witness_name(attempt_id: str) -> str:
    if not re.fullmatch(
        (
            r"(?:bounded-smoke-attempt|translation-attempt|"
            r"release-browser-attempt)-[0-9]{2,}"
        ),
        attempt_id,
    ):
        raise AttemptLedgerError("attempt identity is invalid")
    return (
        f"{_ATTEMPT_CONTEXT_WITNESS_PREFIX}"
        f"{attempt_id}.json"
    )


def _attempt_context_witness_binding(
    binding: _BoundLedgerPath,
    attempt_id: str,
) -> _BoundLedgerPath:
    return _sibling_binding(
        binding,
        _attempt_context_witness_name(attempt_id),
    )


def _write_attempt_context_witness(
    *,
    binding: _BoundLedgerPath,
    attempt_id: str,
    context: Mapping[str, object],
) -> None:
    _write_bound_immutable_json(
        binding=_attempt_context_witness_binding(
            binding,
            attempt_id,
        ),
        payload=context,
        label="attempt context witness",
    )


def _remove_attempt_context_witness(
    *,
    binding: _BoundLedgerPath,
    attempt_id: str,
    context: Mapping[str, object],
) -> None:
    _unlink_expected_bound_file(
        _attempt_context_witness_binding(
            binding,
            attempt_id,
        ),
        expected=_canonical_bytes(context),
        label="attempt context witness",
        allowed_link_counts=frozenset({1}),
    )


def _authorization_receipt_payload(
    *,
    ledger: Path,
    authorization: Mapping[str, object],
    revision: Mapping[str, object],
) -> dict[str, object]:
    immutable_authorization = {
        key: authorization.get(key)
        for key in sorted(_AUTHORIZATION_IMMUTABLE_KEYS)
    }
    return {
        "schema_version": _AUTHORIZATION_RECEIPT_SCHEMA,
        "ledger_path": str(ledger),
        "authorization_id": authorization["authorization_id"],
        "authorization_sha256": sha256(
            _canonical_bytes(immutable_authorization)
        ).hexdigest(),
        "ledger_revision": revision["revision"],
        "ledger_revision_hash": revision["revision_hash"],
    }


def _write_authorization_receipt(
    *,
    binding: _BoundLedgerPath,
    payload: Mapping[str, object],
) -> None:
    authorization_id = payload.get("authorization_id")
    if not isinstance(authorization_id, str):
        raise AttemptLedgerError(
            "authorization receipt is invalid"
        )
    receipt_binding = _authorization_receipt_binding(
        binding,
        authorization_id,
    )
    _write_bound_immutable_json(
        binding=receipt_binding,
        payload=payload,
        label="authorization receipt",
    )


def _read_authorization_receipt(
    *,
    binding: _BoundLedgerPath,
    name: str,
) -> dict[str, Any]:
    receipt_binding = _BoundLedgerPath(
        path=binding.path.with_name(name),
        parent_descriptor=binding.parent_descriptor,
        parent_identity=binding.parent_identity,
    )
    content = _read_regular_file_once(
        receipt_binding.path,
        label="authorization receipt",
        binding=receipt_binding,
    )
    payload = _decode_json_object_bytes(
        content,
        label="authorization receipt",
    )
    if _canonical_bytes(payload) != content:
        raise AttemptLedgerError(
            "authorization receipt content mismatch"
        )
    return payload


def _authorization_revision(
    payload: Mapping[str, object],
    *,
    authorization_id: str,
) -> Mapping[str, object]:
    chain = payload.get("revision_chain")
    if not isinstance(chain, list):
        raise AttemptLedgerError(
            "authorization receipt does not match ledger"
        )
    matches = [
        entry
        for entry in chain
        if (
            isinstance(entry, dict)
            and entry.get("operation") == "authorization_created"
            and entry.get("authorization_id") == authorization_id
        )
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise AttemptLedgerError(
            "authorization receipt does not match ledger"
        )
    authorizations = payload.get("authorizations")
    if not isinstance(authorizations, list):
        raise AttemptLedgerError(
            "authorization receipt does not match ledger"
        )
    current = [
        authorization
        for authorization in authorizations
        if (
            isinstance(authorization, dict)
            and authorization.get("authorization_id") == authorization_id
        )
    ]
    checkpoint_matches: list[Mapping[str, object]] = []
    for entry in chain:
        if (
            not isinstance(entry, dict)
            or entry.get("operation") != "state_checkpoint"
        ):
            continue
        snapshot = entry.get("state_snapshot")
        snapshot_authorizations = (
            snapshot.get("authorizations")
            if isinstance(snapshot, dict)
            else None
        )
        if not isinstance(snapshot_authorizations, list):
            continue
        historical = [
            authorization
            for authorization in snapshot_authorizations
            if (
                isinstance(authorization, dict)
                and authorization.get("authorization_id")
                == authorization_id
            )
        ]
        if (
            len(current) == 1
            and len(historical) == 1
            and all(
                historical[0].get(key) == current[0].get(key)
                for key in _AUTHORIZATION_IMMUTABLE_KEYS
            )
        ):
            checkpoint_matches.append(entry)
    if len(checkpoint_matches) != 1:
        raise AttemptLedgerError(
            "authorization receipt does not match ledger"
        )
    return checkpoint_matches[0]


def _verify_authorization_receipts(
    *,
    binding: _BoundLedgerPath,
    payload: Mapping[str, object],
    allowed_missing_authorization_ids: frozenset[str] = frozenset(),
) -> set[str]:
    names = tuple(
        name
        for name in os.listdir(binding.parent_descriptor)
        if (
            name.startswith(_AUTHORIZATION_RECEIPT_PREFIX)
            and name.endswith(".json")
        )
    )
    verified: set[str] = set()
    authorizations = payload.get("authorizations")
    if not isinstance(authorizations, list):
        raise AttemptLedgerError("canonical ledger is invalid")
    authorization_ids = {
        authorization.get("authorization_id")
        for authorization in authorizations
        if (
            isinstance(authorization, dict)
            and isinstance(
                authorization.get("authorization_id"),
                str,
            )
        )
    }
    if len(authorization_ids) != len(authorizations):
        raise AttemptLedgerError("canonical ledger is invalid")
    present_authorization_ids: set[str] = set()
    for name in names:
        authorization_id = name[
            len(_AUTHORIZATION_RECEIPT_PREFIX) : -len(".json")
        ]
        present_authorization_ids.add(authorization_id)
        matches = [
            authorization
            for authorization in authorizations
            if (
                isinstance(authorization, dict)
                and authorization.get("authorization_id")
                == authorization_id
            )
        ]
        revision = (
            _authorization_revision(
                payload,
                authorization_id=str(authorization_id),
            )
            if len(matches) == 1
            else None
        )
        receipt_was_complete = False
        if len(matches) == 1 and revision is not None:
            expected_receipt = _authorization_receipt_payload(
                ledger=binding.path,
                authorization=matches[0],
                revision=revision,
            )
            receipt_binding = _authorization_receipt_binding(
                binding,
                authorization_id,
            )
            receipt_was_complete = (
                _read_bound_file_if_present(
                    receipt_binding,
                    label="authorization receipt",
                    allowed_link_counts=frozenset({1, 2}),
                )
                == _canonical_bytes(expected_receipt)
            )
            _write_authorization_receipt(
                binding=binding,
                payload=expected_receipt,
            )
        receipt = _read_authorization_receipt(
            binding=binding,
            name=name,
        )
        immutable_authorization = (
            {
                key: matches[0].get(key)
                for key in sorted(_AUTHORIZATION_IMMUTABLE_KEYS)
            }
            if len(matches) == 1
            else None
        )
        if (
            not isinstance(authorization_id, str)
            or name != _authorization_receipt_name(authorization_id)
            or set(receipt)
            != {
                "schema_version",
                "ledger_path",
                "authorization_id",
                "authorization_sha256",
                "ledger_revision",
                "ledger_revision_hash",
            }
            or receipt.get("schema_version")
            != _AUTHORIZATION_RECEIPT_SCHEMA
            or receipt.get("ledger_path") != str(binding.path)
            or len(matches) != 1
            or receipt.get("authorization_sha256")
            != sha256(
                _canonical_bytes(immutable_authorization)
            ).hexdigest()
            or revision is None
            or receipt.get("ledger_revision")
            != revision.get("revision")
            or receipt.get("ledger_revision_hash")
            != revision.get("revision_hash")
        ):
            raise AttemptLedgerError(
                "authorization rollback detected"
            )
        if receipt_was_complete:
            verified.add(authorization_id)
    if (
        authorization_ids - present_authorization_ids
        - allowed_missing_authorization_ids
    ):
        raise AttemptLedgerError(
            "authorization receipt is missing"
        )
    return verified


def _verify_persisted_attempt_contexts(
    *,
    binding: _BoundLedgerPath,
    payload: Mapping[str, object],
) -> None:
    authorizations = payload.get("authorizations")
    attempts = payload.get("attempts")
    if (
        not isinstance(authorizations, list)
        or not isinstance(attempts, list)
    ):
        raise AttemptLedgerError("canonical ledger is invalid")
    known_authorizations = {
        authorization.get("authorization_id")
        for authorization in authorizations
        if (
            isinstance(authorization, dict)
            and isinstance(
                authorization.get("authorization_id"),
                str,
            )
        )
    }
    known_attempts = {
        attempt.get("attempt_id")
        for attempt in attempts
        if (
            isinstance(attempt, dict)
            and isinstance(attempt.get("attempt_id"), str)
        )
    }
    search_roots = [binding.path.parent]
    repository_root = _REPO_ROOT.resolve()
    try:
        binding.path.relative_to(repository_root)
    except ValueError:
        pass
    else:
        if repository_root != binding.path.parent:
            search_roots.append(repository_root)
    context_sources: list[tuple[Path, str | None]] = [
        (path, None)
        for root in search_roots
        for path in root.rglob("attempt-context.json")
    ]
    for name in os.listdir(binding.parent_descriptor):
        if not (
            name.startswith(_ATTEMPT_CONTEXT_WITNESS_PREFIX)
            and name.endswith(".json")
        ):
            continue
        attempt_id = name[
            len(_ATTEMPT_CONTEXT_WITNESS_PREFIX) : -len(".json")
        ]
        if name != _attempt_context_witness_name(attempt_id):
            raise AttemptLedgerError(
                "persisted attempt context is invalid"
            )
        context_sources.append(
            (binding.path.with_name(name), attempt_id)
        )
    for context_path, witness_attempt_id in context_sources:
        context, _ = _read_attempt_context_once(context_path)
        if context.get("ledger_path") != str(binding.path):
            if witness_attempt_id is not None:
                raise AttemptLedgerError(
                    "persisted attempt context is invalid"
                )
            continue
        phase_attempts = context.get("phase_attempt_ids")
        phase_authorizations = context.get(
            "phase_authorization_ids"
        )
        if (
            not isinstance(phase_attempts, dict)
            or not isinstance(phase_authorizations, dict)
        ):
            raise AttemptLedgerError(
                "persisted attempt context is invalid"
            )
        referenced_attempts = {
            attempt_id
            for attempt_id in phase_attempts.values()
            if isinstance(attempt_id, str)
        }
        referenced = {
            authorization_id
            for authorization_id in phase_authorizations.values()
            if isinstance(authorization_id, str)
        }
        if (
            len(referenced_attempts) != len(phase_attempts)
            or not referenced_attempts <= known_attempts
            or len(referenced) != len(phase_authorizations)
            or not referenced <= known_authorizations
        ):
            raise AttemptLedgerError(
                "authorization rollback detected"
            )
        if (
            witness_attempt_id is not None
            and phase_attempts.get(
                attempt_context_phase(context)
            )
            != witness_attempt_id
        ):
            raise AttemptLedgerError(
                "persisted attempt context is invalid"
            )


def read_ledger_checkpoint_source(
    path: str | Path,
) -> tuple[dict[str, Any], bytes]:
    ledger = _canonical_ledger_path(path)
    with _ledger_lock(ledger) as binding:
        _recover_orphan_temp(ledger, binding=binding)
        content = _read_regular_file_once(
            ledger,
            label="ledger checkpoint source",
            binding=binding,
        )
        payload = _validate_ledger(
            _decode_json_object_bytes(
                content,
                label="ledger checkpoint source",
            ),
            expected_path=ledger,
            allow_uncheckpointed=True,
        )
        _verify_terminal_evidence_manifests(payload)
        _verify_failure_reclassifications(payload)
        return deepcopy(payload), content


def read_ledger(path: str | Path) -> dict[str, Any]:
    ledger = _canonical_ledger_path(path)
    with _ledger_lock(ledger) as binding:
        _recover_orphan_temp(ledger, binding=binding)
        return deepcopy(
            _read_ledger_unlocked(ledger, binding=binding)
        )


def compare_and_swap_ledger(
    path: str | Path,
    *,
    expected_revision: int,
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    ledger = _canonical_ledger_path(path)
    with _ledger_lock(ledger) as binding:
        _recover_orphan_temp(ledger, binding=binding)
        current = _read_ledger_unlocked(ledger, binding=binding)
        if current["revision"] != expected_revision:
            raise AttemptLedgerError("stale ledger revision")
        replacement = mutate(deepcopy(current))
        if not isinstance(replacement, dict):
            raise AttemptLedgerError(
                "ledger mutation must return an object"
            )
        if replacement.get("attempts") != current["attempts"]:
            raise AttemptLedgerError(
                "generic ledger mutation cannot change attempts"
            )
        if replacement.get("authorizations") != current[
            "authorizations"
        ]:
            raise AttemptLedgerError(
                "generic ledger mutation cannot change authorizations"
            )
        replacement["revision"] = expected_revision + 1
        replacement["circuit_state"] = _circuit_state(replacement)
        if replacement.get("revision_chain") != current["revision_chain"]:
            raise AttemptLedgerError(
                "ledger revision chain cannot be replaced"
            )
        _append_revision(
            replacement,
            operation="compare_and_swap",
        )
        _atomic_write_ledger(ledger, replacement, binding=binding)
        return deepcopy(replacement)


def _readiness(path: Path) -> dict[str, Any]:
    payload = _load_json_object(path, label="readiness")
    required_true = (
        "step_0_passed",
        "step_0_5_passed",
        "step_4_5_passed",
        "affected_zero_api_passed",
        "desktop_fixture_passed",
        "mobile_fixture_passed",
    )
    if (
        not isinstance(payload.get("plan_revision"), str)
        or not payload.get("plan_revision")
        or not isinstance(payload.get("ledger_path"), str)
        or not Path(str(payload["ledger_path"])).is_absolute()
        or payload.get("circuit_state") != "closed"
        or payload.get("invalid_clarification_count") != 0
        or not isinstance(payload.get("ledger_anchor_revision"), int)
        or isinstance(payload.get("ledger_anchor_revision"), bool)
        or payload["ledger_anchor_revision"] < 0
        or not _is_sha256(
            payload.get("reviewed_candidate_manifest_sha256")
        )
        or not _is_sha256(payload.get("ledger_anchor_hash"))
        or any(payload.get(field) is not True for field in required_true)
    ):
        raise AttemptLedgerError("readiness is not eligible")
    return payload


def _verify_current_readiness(
    *,
    readiness_path: Path,
    ledger_path: Path,
    expected_manifest_sha256: str,
) -> None:
    from tools.guide_gates.build_task11_readiness import (
        verify_task11_readiness,
    )

    try:
        verify_task11_readiness(
            readiness_path=readiness_path,
            ledger_path=ledger_path,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    except (OSError, ValueError) as exc:
        raise AttemptLedgerError(
            "readiness evidence drift"
        ) from exc


def _capture_readiness_binding(
    path: Path,
) -> tuple[str, tuple[tuple[Path, str | None], ...]]:
    readiness_bytes = _read_regular_file_once(path, label="readiness")
    readiness = _decode_json_object_bytes(
        readiness_bytes,
        label="readiness",
    )
    evidence_files = readiness.get("evidence_files")
    evidence_sha256 = readiness.get("evidence_sha256")
    if (
        not isinstance(evidence_files, dict)
        or not isinstance(evidence_sha256, dict)
        or set(evidence_files) != set(evidence_sha256)
    ):
        raise AttemptLedgerError("readiness evidence drift")
    bound_paths: dict[Path, str | None] = {}
    candidate_manifest: dict[str, Any] | None = None
    candidate_manifest_path: Path | None = None
    candidate_manifest_sha256: str | None = None
    for role in sorted(evidence_files):
        evidence_path = Path(str(evidence_files[role]))
        evidence_bytes = _read_regular_file_once(
            evidence_path,
            label=f"readiness evidence {role}",
        )
        digest = sha256(evidence_bytes).hexdigest()
        if evidence_sha256[role] != digest:
            raise AttemptLedgerError("readiness evidence drift")
        bound_paths[evidence_path] = digest
        evidence_payload = _decode_json_object_bytes(
            evidence_bytes,
            label=f"readiness evidence {role}",
        )
        artifact_index = evidence_payload.get(
            "artifact_sha256_by_path"
        )
        if isinstance(artifact_index, dict):
            for relative, expected_sha256 in artifact_index.items():
                artifact_path = (
                    evidence_path.parent / str(relative)
                ).resolve()
                artifact_bytes = _read_regular_file_once(
                    artifact_path,
                    label="readiness artifact",
                )
                artifact_sha256 = sha256(artifact_bytes).hexdigest()
                if expected_sha256 != artifact_sha256:
                    raise AttemptLedgerError(
                        "readiness evidence drift"
                    )
                bound_paths[artifact_path] = artifact_sha256
        if role == "candidate_manifest":
            candidate_manifest = evidence_payload
            candidate_manifest_path = evidence_path.resolve()
            candidate_manifest_sha256 = digest
    if (
        candidate_manifest is not None
        and candidate_manifest_path is not None
        and candidate_manifest_sha256 is not None
    ):
        protected = candidate_manifest.get("protected_paths")
        deleted = candidate_manifest.get("deleted_paths")
        repair_epoch = candidate_manifest.get("repair_epoch")
        if (
            candidate_manifest.get("schema_version")
            != "guide-task11-candidate-manifest-v1"
            or candidate_manifest_sha256
            != readiness.get("reviewed_candidate_manifest_sha256")
            or not isinstance(protected, list)
            or not isinstance(deleted, list)
            or not isinstance(repair_epoch, int)
            or isinstance(repair_epoch, bool)
            or repair_epoch < 1
            or any(
                not isinstance(relative, str)
                or not relative
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                for relative in (*protected, *deleted)
            )
        ):
            raise AttemptLedgerError("readiness evidence drift")
        root = _manifest_repository_root(
            candidate_manifest.get("repository_root"),
            error_message="readiness evidence drift",
        )
        if not _candidate_manifest_path_is_valid(
            root=root,
            path=candidate_manifest_path,
            repair_epoch=repair_epoch,
            plan_revision=candidate_manifest.get("plan_revision"),
        ):
            raise AttemptLedgerError("readiness evidence drift")
        for relative in protected:
            protected_path = (root / str(relative)).resolve()
            bound_paths[protected_path] = sha256(
                _read_regular_file_once(
                    protected_path,
                    label="protected readiness payload",
                )
            ).hexdigest()
        for relative in deleted:
            deleted_path = (root / str(relative)).resolve()
            if deleted_path.exists() or deleted_path.is_symlink():
                raise AttemptLedgerError("readiness evidence drift")
            bound_paths[deleted_path] = None
    return (
        sha256(readiness_bytes).hexdigest(),
        tuple(
            sorted(
                bound_paths.items(),
                key=lambda item: str(item[0]),
            )
        ),
    )


def _require_current_readiness_binding(
    *,
    readiness_path: Path,
    binding: tuple[str, tuple[tuple[Path, str | None], ...]],
) -> None:
    readiness_sha256, evidence_binding = binding
    if (
        sha256(
            _read_regular_file_once(
                readiness_path,
                label="readiness",
            )
        ).hexdigest()
        != readiness_sha256
    ):
        raise AttemptLedgerError("readiness evidence drift")
    for evidence_path, expected_sha256 in evidence_binding:
        if expected_sha256 is None:
            if evidence_path.exists() or evidence_path.is_symlink():
                raise AttemptLedgerError("readiness evidence drift")
            continue
        if (
            sha256(
                _read_regular_file_once(
                    evidence_path,
                    label="readiness evidence",
                )
            ).hexdigest()
            != expected_sha256
        ):
            raise AttemptLedgerError("readiness evidence drift")


def _independent_audit(
    *,
    path: Path,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    evidence_files = readiness.get("evidence_files")
    evidence_sha256 = readiness.get("evidence_sha256")
    if (
        not isinstance(evidence_files, dict)
        or not isinstance(evidence_sha256, dict)
        or Path(str(evidence_files.get("independent_audit"))).resolve()
        != path.resolve()
        or evidence_sha256.get("independent_audit")
        != _file_sha256(path)
    ):
        raise AttemptLedgerError(
            "independent audit is not bound to readiness"
        )
    audit = _load_json_object(path, label="independent audit")
    if (
        audit.get("passed") is not True
        or audit.get("plan_revision")
        != readiness.get("plan_revision")
        or audit.get("protected_payload_sha256")
        != readiness.get("protected_payload_sha256")
    ):
        raise AttemptLedgerError("independent audit is invalid")
    return audit


def _latest_failure(
    payload: dict[str, Any],
    *,
    plan_revision: str,
) -> dict[str, Any] | None:
    return next(
        (
            attempt
            for attempt in reversed(payload["attempts"])
            if isinstance(attempt, dict)
            and attempt.get("plan_revision") == plan_revision
            and attempt.get("result") == "failed"
        ),
        None,
    )


def _retry_source_failure(
    payload: dict[str, Any],
    *,
    plan_revision: str,
) -> dict[str, Any] | None:
    previous = _latest_failure(
        payload,
        plan_revision=plan_revision,
    )
    if previous is not None:
        return previous
    has_current_revision_attempt = any(
        isinstance(attempt, dict)
        and attempt.get("plan_revision") == plan_revision
        for attempt in payload["attempts"]
    )
    if has_current_revision_attempt:
        return None
    return next(
        (
            attempt
            for attempt in reversed(payload["attempts"])
            if isinstance(attempt, dict)
            and attempt.get("result") == "failed"
        ),
        None,
    )


def _retry_authorization_from_verified_ledger(
    payload: dict[str, Any],
    *,
    plan_revision: str,
) -> tuple[str, int, dict[str, str | None]]:
    previous = _latest_failure(
        payload,
        plan_revision=plan_revision,
    )
    if previous is None:
        previous = _retry_source_failure(
            payload,
            plan_revision=plan_revision,
        )
    if previous is None:
        return (
            "planned_gate",
            0,
            {
                "local_reproduction": None,
                "focused_test": None,
                "shared_owner_repair": None,
            },
        )
    owner = previous.get("first_failure_owner")
    if not isinstance(owner, str) or not owner:
        raise AttemptLedgerError("historical failure owner is invalid")
    history = previous.get("failure_reclassifications")
    if (
        not isinstance(history, list)
        or not history
        or not isinstance(history[-1], dict)
    ):
        raise AttemptLedgerError(
            "latest failure has no verified repair closure"
        )
    repair_files = history[-1].get("repair_evidence_files")
    if not isinstance(repair_files, dict):
        raise AttemptLedgerError(
            "latest failure has no verified repair closure"
        )
    repair_evidence = {
        "local_reproduction": repair_files.get(
            "pre_fix_reproduction"
        ),
        "focused_test": repair_files.get("focused_zero_api"),
        "shared_owner_repair": repair_files.get("repair_patch"),
    }
    if not all(
        isinstance(value, str) and value
        for value in repair_evidence.values()
    ):
        raise AttemptLedgerError(
            "latest failure has no verified repair closure"
        )
    return (
        owner,
        _failure_counts(
            payload,
            plan_revision=plan_revision,
        ).get(owner, 0),
        repair_evidence,
    )


def _verify_retry_repair_artifacts(
    payload: dict[str, Any],
    *,
    plan_revision: str,
) -> None:
    previous = _retry_source_failure(
        payload,
        plan_revision=plan_revision,
    )
    if previous is None:
        return
    failure_code = previous.get("failure_code")
    expected_owner = _RECLASSIFICATION_OWNER_BY_CODE.get(failure_code)
    if (
        expected_owner is None
        or previous.get("first_failure_owner") != expected_owner
    ):
        raise AttemptLedgerError("retry repair evidence is invalid")
    if failure_code not in _ACTIVE_RECLASSIFICATION_CODES:
        return
    history = previous.get("failure_reclassifications")
    repair_files = (
        history[-1].get("repair_evidence_files")
        if isinstance(history, list)
        and history
        and isinstance(history[-1], dict)
        else None
    )
    if not isinstance(repair_files, dict):
        raise AttemptLedgerError("retry repair evidence is invalid")
    _validate_reclassification_repair(
        failure_code=str(failure_code),
        repair_files=repair_files,
        error_message="retry repair evidence is invalid",
    )


def _validate_reclassification_repair(
    *,
    failure_code: str,
    repair_files: Mapping[str, object],
    error_message: str,
) -> None:
    try:
        from tools.guide_gates.run_task11_independent_audit import (
            validate_persisted_image_planning_repair_evidence,
            validate_runtime_request_authority_repair_evidence,
            validate_runtime_shell_lease_repair_evidence,
            validate_zero_card_feedback_repair_evidence,
        )

        validators = {
            "runtime_shell_authority_lease_timeout": (
                validate_runtime_shell_lease_repair_evidence
            ),
            "runtime_version_sync_authority_check_timeout": (
                validate_runtime_request_authority_repair_evidence
            ),
            "zero_card_feedback_target_lookup": (
                validate_zero_card_feedback_repair_evidence
            ),
            "missing_persisted_image_scenario_inputs": (
                validate_persisted_image_planning_repair_evidence
            ),
        }
        validator = validators.get(failure_code)
        if validator is None:
            raise AttemptLedgerError(
                "unsupported failure reclassification"
            )
        validator(
            repair_files=repair_files,
            repo_root=Path(__file__).resolve().parents[2],
        )
    except AttemptLedgerError:
        raise
    except Exception as error:
        raise AttemptLedgerError(error_message) from error


def authorize_attempt(
    *,
    phase: Phase,
    readiness_path: str | Path,
    ledger_path: str | Path,
    independent_audit_path: str | Path,
    expected_manifest_sha256: str,
    readiness_verifier: Callable[..., dict[str, Any]] | None = None,
) -> str:
    readiness_file = Path(readiness_path)
    audit_file = Path(independent_audit_path)
    ledger = _canonical_ledger_path(ledger_path)
    if readiness_verifier is None:
        from tools.guide_gates.build_task11_readiness import (
            verify_task11_readiness,
        )

        readiness_verifier = verify_task11_readiness
    verified_readiness = readiness_verifier(
        readiness_path=readiness_file,
        ledger_path=ledger,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if not _is_sha256(expected_manifest_sha256):
        raise AttemptLedgerError(
            "reviewed candidate manifest SHA-256 is invalid"
        )
    try:
        readiness_bytes = readiness_file.read_bytes()
        audit_bytes = audit_file.read_bytes()
    except OSError as exc:
        raise AttemptLedgerError(
            "authorization evidence is unavailable"
        ) from exc
    readiness = _readiness(readiness_file)
    if readiness.get("ledger_path") != str(ledger):
        raise AttemptLedgerError(
            "authorization ledger path mismatch"
        )
    if (
        verified_readiness != readiness
        or readiness.get("reviewed_candidate_manifest_sha256")
        != expected_manifest_sha256
        or readiness_file.read_bytes() != readiness_bytes
    ):
        raise AttemptLedgerError(
            "readiness changed during authorization"
        )
    audit = _independent_audit(path=audit_file, readiness=readiness)
    if audit_file.read_bytes() != audit_bytes:
        raise AttemptLedgerError(
            "independent audit changed during authorization"
        )
    readiness_sha256 = sha256(readiness_bytes).hexdigest()
    audit_sha256 = sha256(audit_bytes).hexdigest()
    preflight_ledger = read_ledger(ledger)
    preflight_failures = _failure_counts(
        preflight_ledger,
        plan_revision=readiness["plan_revision"],
    )
    if any(count >= 2 for count in preflight_failures.values()):
        raise AttemptLedgerError("smoke circuit is open")
    _verify_retry_repair_artifacts(
        preflight_ledger,
        plan_revision=readiness["plan_revision"],
    )
    preflight_revision = preflight_ledger["revision"]
    preflight_revision_hash = preflight_ledger[
        "revision_chain"
    ][-1]["revision_hash"]
    with _ledger_lock(ledger) as binding:
        _recover_orphan_temp(ledger, binding=binding)
        if (
            readiness_file.read_bytes() != readiness_bytes
            or audit_file.read_bytes() != audit_bytes
        ):
            raise AttemptLedgerError(
                "authorization evidence changed before ledger binding"
            )
        payload = _read_ledger_unlocked(ledger, binding=binding)
        if (
            payload["revision"] != preflight_revision
            or payload["revision_chain"][-1]["revision_hash"]
            != preflight_revision_hash
        ):
            raise AttemptLedgerError(
                "ledger changed during repair validation"
            )
        _verify_persisted_attempt_contexts(
            binding=binding,
            payload=payload,
        )
        verify_ledger_extension(
            payload,
            anchor_revision=readiness["ledger_anchor_revision"],
            anchor_hash=readiness["ledger_anchor_hash"],
        )
        plan_revision = readiness["plan_revision"]
        if any(
            isinstance(attempt, dict)
            and attempt.get("plan_revision") == plan_revision
            and attempt.get("trajectory_set") == phase
            and attempt.get("result") == "passed"
            for attempt in payload["attempts"]
        ):
            raise AttemptLedgerError("phase already passed")
        failures = _failure_counts(
            payload,
            plan_revision=plan_revision,
        )
        if any(count >= 2 for count in failures.values()):
            raise AttemptLedgerError("smoke circuit is open")
        owner, repair_epoch, repair_evidence = (
            _retry_authorization_from_verified_ledger(
                payload,
                plan_revision=plan_revision,
            )
        )
        authorization_id = "auth_" + sha256(
            _canonical_bytes({
                "phase": phase,
                "plan_revision": plan_revision,
                "repair_epoch": repair_epoch,
                "first_failure_owner": owner,
                "readiness_path": str(readiness_file.resolve()),
                "readiness_sha256": readiness_sha256,
                "expected_manifest_sha256": (
                    expected_manifest_sha256
                ),
                "independent_audit_path": str(audit_file.resolve()),
                "independent_audit_sha256": audit_sha256,
                "repair_evidence": repair_evidence,
            })
        ).hexdigest()[:32]
        existing_authorizations = [
            authorization
            for authorization in payload["authorizations"]
            if (
                isinstance(authorization, dict)
                and authorization.get("authorization_id")
                == authorization_id
            )
        ]
        if len(existing_authorizations) > 1:
            raise AttemptLedgerError(
                "authorization identity is duplicated"
            )
        verified_receipts = _verify_authorization_receipts(
            binding=binding,
            payload=payload,
            allowed_missing_authorization_ids=(
                frozenset({authorization_id})
                if existing_authorizations
                else frozenset()
            ),
        )
        if existing_authorizations:
            if authorization_id in verified_receipts:
                raise AttemptLedgerError(
                    "authorization already issued"
                )
            revision = _authorization_revision(
                payload,
                authorization_id=authorization_id,
            )
            _write_authorization_receipt(
                binding=binding,
                payload=_authorization_receipt_payload(
                    ledger=ledger,
                    authorization=existing_authorizations[0],
                    revision=revision,
                ),
            )
            return authorization_id
        if any(
            authorization.get("plan_revision") == plan_revision
            and authorization.get("state") in {"allocated", "consumed"}
            for authorization in payload["authorizations"]
            if isinstance(authorization, dict)
        ):
            raise AttemptLedgerError(
                "plan revision already has an active authorization"
            )
        authorization = {
            "authorization_id": authorization_id,
            "phase": phase,
            "plan_revision": plan_revision,
            "repair_epoch": repair_epoch,
            "first_failure_owner": owner,
            "readiness_path": str(readiness_file.resolve()),
            "readiness_sha256": readiness_sha256,
            "expected_manifest_sha256": expected_manifest_sha256,
            "independent_audit_path": str(audit_file.resolve()),
            "independent_audit_sha256": audit_sha256,
            "repair_evidence": repair_evidence,
            "state": "allocated",
            "attempt_id": None,
            "created_at": _utc_now(),
        }
        payload["authorizations"].append(authorization)
        payload["revision"] += 1
        payload["circuit_state"] = _circuit_state(payload)
        revision = _append_revision(
            payload,
            operation="authorization_created",
            authorization_id=authorization_id,
        )
        _atomic_write_ledger(ledger, payload, binding=binding)
        _write_authorization_receipt(
            binding=binding,
            payload=_authorization_receipt_payload(
                ledger=ledger,
                authorization=authorization,
                revision=revision,
            ),
        )
        return authorization_id


def _authorization(
    payload: dict[str, Any],
    authorization_id: str,
) -> dict[str, Any]:
    matches = [
        item
        for item in payload["authorizations"]
        if isinstance(item, dict)
        and item.get("authorization_id") == authorization_id
    ]
    if len(matches) != 1:
        raise AttemptLedgerError("authorization is unknown")
    return matches[0]


def _next_attempt_id(
    payload: dict[str, Any],
    *,
    phase: Phase,
) -> str:
    prefix = {
        "bounded": "bounded-smoke-attempt",
        "translation": "translation-attempt",
        "browser": "release-browser-attempt",
    }[phase]
    used = {
        attempt.get("attempt_id")
        for attempt in payload["attempts"]
        if isinstance(attempt, dict)
    }
    ordinal = 1
    while f"{prefix}-{ordinal:02d}" in used:
        ordinal += 1
    return f"{prefix}-{ordinal:02d}"


def allocate_attempt(
    *,
    phase: Phase,
    authorization_id: str,
    ledger_path: str | Path,
    readiness_path: str | Path,
    output_root: str | Path,
    parent_context: str | Path | None = None,
    require_summary_phase: str | None = None,
    require_summary_result: str | None = None,
) -> Path:
    readiness_file = Path(readiness_path)
    readiness = _readiness(readiness_file)
    ledger = Path(ledger_path)
    parent = (
        read_attempt_context(
            parent_context,
            ledger_path=ledger,
            readiness_path=readiness_file,
        )
        if parent_context is not None
        else None
    )
    if parent is None:
        if (
            require_summary_phase is not None
            or require_summary_result is not None
        ):
            raise AttemptLedgerError(
                "parent summary requirement needs a parent context"
            )
        parent_summary = None
    else:
        if (
            require_summary_phase is None
            or require_summary_result is None
        ):
            raise AttemptLedgerError(
                "child allocation requires a parent summary contract"
            )
        parent_summary = _required_parent_summary(
            parent,
            phase=require_summary_phase,
            result=require_summary_result,
        )
    with _ledger_lock(ledger) as binding:
        _recover_orphan_temp(ledger, binding=binding)
        payload = _read_ledger_unlocked(ledger, binding=binding)
        verified_receipts = _verify_authorization_receipts(
            binding=binding,
            payload=payload,
        )
        if authorization_id not in verified_receipts:
            raise AttemptLedgerError(
                "authorization receipt is missing"
            )
        verify_ledger_extension(
            payload,
            anchor_revision=readiness["ledger_anchor_revision"],
            anchor_hash=readiness["ledger_anchor_hash"],
        )
        if parent is not None:
            parent_phase = attempt_context_phase(parent)
            parent_ids = parent["phase_attempt_ids"]
            parent_attempt_id = parent_ids[parent_phase]
            parent_attempts = [
                item
                for item in payload["attempts"]
                if (
                    isinstance(item, dict)
                    and item.get("attempt_id") == parent_attempt_id
                )
            ]
            if (
                phase != "browser"
                or parent_phase != "translation"
                or len(parent_attempts) != 1
                or parent_attempts[0].get("result") != "passed"
                or parent_attempts[0].get("context_path")
                != str(Path(parent_context).resolve())
            ):
                raise AttemptLedgerError(
                    "parent translation attempt has not passed"
                )
        authorization = _authorization(payload, authorization_id)
        if authorization.get("state") != "allocated":
            raise AttemptLedgerError("authorization is not allocatable")
        if (
            authorization.get("phase") != phase
            or authorization.get("plan_revision")
            != readiness.get("plan_revision")
            or authorization.get("readiness_path")
            != str(readiness_file.resolve())
            or authorization.get("readiness_sha256")
            != _file_sha256(readiness_file)
            or authorization.get("expected_manifest_sha256")
            != readiness.get(
                "reviewed_candidate_manifest_sha256"
            )
        ):
            raise AttemptLedgerError(
                "authorization does not match allocation"
            )
        ledger_parent = ledger.resolve().parent
        supplied_output_root = Path(output_root).expanduser()
        canonical_output_root = supplied_output_root.resolve()
        try:
            canonical_output_root.relative_to(ledger_parent)
        except ValueError as exc:
            raise AttemptLedgerError(
                "attempt output root is outside ledger authority"
            ) from exc
        if (
            Path(os.path.abspath(supplied_output_root))
            != canonical_output_root
            or supplied_output_root.is_symlink()
        ):
            raise AttemptLedgerError(
                "attempt output root is outside ledger authority"
            )
        existing_attempt_id = authorization.get("attempt_id")
        if existing_attempt_id is not None:
            existing_attempts = [
                item
                for item in payload["attempts"]
                if (
                    isinstance(item, dict)
                    and item.get("attempt_id") == existing_attempt_id
                )
            ]
            if (
                not isinstance(existing_attempt_id, str)
                or len(existing_attempts) != 1
            ):
                raise AttemptLedgerError(
                    "authorization already has an attempt"
                )
            existing_attempt = existing_attempts[0]
            existing_context_path = Path(
                str(existing_attempt.get("context_path"))
            )
            expected_output = (
                canonical_output_root / existing_attempt_id
            )
            if (
                existing_context_path
                != expected_output / "attempt-context.json"
                or existing_attempt.get("trajectory_set") != phase
            ):
                raise AttemptLedgerError(
                    "authorization already has an attempt"
                )
            existing_context, context_sha256 = (
                _read_attempt_context_once(existing_context_path)
            )
            _validate_context_allocation(
                payload=payload,
                context=existing_context,
                context_path=existing_context_path,
                context_sha256=context_sha256,
                attempt=existing_attempt,
            )
            _verify_persisted_attempt_contexts(
                binding=binding,
                payload=payload,
            )
            _write_attempt_context_witness(
                binding=binding,
                attempt_id=existing_attempt_id,
                context=existing_context,
            )
            return existing_context_path

        attempt_id = _next_attempt_id(payload, phase=phase)
        output_directory = canonical_output_root / attempt_id
        expected_parent_attempt_id = None
        expected_phase_attempt_ids = {phase: attempt_id}
        expected_phase_authorization_ids = {
            phase: authorization_id,
        }
        if parent is not None:
            parent_phase = attempt_context_phase(parent)
            expected_parent_attempt_id = parent[
                "phase_attempt_ids"
            ][parent_phase]
            expected_phase_attempt_ids = {
                **parent["phase_attempt_ids"],
                phase: attempt_id,
            }
            expected_phase_authorization_ids = {
                **parent["phase_authorization_ids"],
                phase: authorization_id,
            }
        try:
            prior_output = next(
                ledger_parent.rglob(attempt_id),
                None,
            )
        except OSError as exc:
            raise AttemptLedgerError(
                "attempt output directory cannot be verified"
            ) from exc
        if prior_output is not None:
            if (
                prior_output != output_directory
                or prior_output.is_symlink()
                or not prior_output.is_dir()
            ):
                raise AttemptLedgerError(
                    "attempt output directory already exists"
                )
            context_path = output_directory / "attempt-context.json"
            witness_binding = _attempt_context_witness_binding(
                binding,
                attempt_id,
            )
            if _ledger_entry_exists(witness_binding):
                raise AttemptLedgerError(
                    "authorization rollback detected"
                )
            if context_path.exists() or context_path.is_symlink():
                orphan_context, _ = _read_attempt_context_once(
                    context_path
                )
                if (
                    orphan_context.get("schema_version")
                    != _CONTEXT_SCHEMA_VERSION
                    or orphan_context.get("current_phase") != phase
                    or orphan_context.get("phase_attempt_ids")
                    != expected_phase_attempt_ids
                    or orphan_context.get("phase_authorization_ids")
                    != expected_phase_authorization_ids
                    or orphan_context.get("parent_attempt_id")
                    != expected_parent_attempt_id
                    or orphan_context.get(
                        "required_parent_summary"
                    )
                    != parent_summary
                    or orphan_context.get("output_directory")
                    != str(output_directory)
                    or orphan_context.get("readiness_path")
                    != str(readiness_file.resolve())
                    or orphan_context.get("readiness_sha256")
                    != _file_sha256(readiness_file)
                    or orphan_context.get(
                        "expected_manifest_sha256"
                    )
                    != authorization["expected_manifest_sha256"]
                    or orphan_context.get("ledger_path")
                    != str(ledger.resolve())
                    or orphan_context.get(
                        "allocated_ledger_revision"
                    )
                    != payload["revision"] + 1
                ):
                    raise AttemptLedgerError(
                        "attempt output directory already exists"
                    )
                _rollback_attempt_allocation(
                    binding=binding,
                    attempt_id=attempt_id,
                    context=orphan_context,
                    output_directory=output_directory,
                    context_path=context_path,
                )
            else:
                try:
                    output_directory.rmdir()
                except OSError as exc:
                    raise AttemptLedgerError(
                        "attempt output directory already exists"
                    ) from exc
                _fsync_directory(output_directory.parent)
        _verify_persisted_attempt_contexts(
            binding=binding,
            payload=payload,
        )
        try:
            output_directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise AttemptLedgerError(
                "attempt output directory already exists"
            ) from exc
        context_path = output_directory / "attempt-context.json"
        next_revision = payload["revision"] + 1
        attempt = {
            "attempt_id": attempt_id,
            "plan_revision": readiness["plan_revision"],
            "repair_epoch": authorization["repair_epoch"],
            "retry_authorization_id": authorization_id,
            "code_revision": readiness["candidate_head"],
            "expected_manifest_sha256": authorization[
                "expected_manifest_sha256"
            ],
            "started_at": _utc_now(),
            "trajectory_set": phase,
            "first_failure_turn_id": None,
            "first_failure_owner": None,
            "failure_code": None,
            "evidence_directory": str(output_directory),
            "local_reproduction": authorization[
                "repair_evidence"
            ].get("local_reproduction"),
            "focused_test": authorization[
                "repair_evidence"
            ].get("focused_test"),
            "shared_owner_repair": authorization[
                "repair_evidence"
            ].get("shared_owner_repair"),
            "independent_audit": authorization[
                "independent_audit_path"
            ],
            "result": "allocated",
            "context_path": str(context_path),
            "allocated_ledger_revision": next_revision,
            "allocated_ledger_hash": None,
            "context_sha256": None,
        }
        authorization["attempt_id"] = attempt_id
        payload["attempts"].append(attempt)
        payload["revision"] = next_revision
        payload["circuit_state"] = _circuit_state(payload)
        allocation_revision = _append_revision(
            payload,
            operation="attempt_allocated",
            attempt_id=attempt_id,
            authorization_id=authorization_id,
        )
        attempt["allocated_ledger_hash"] = allocation_revision[
            "revision_hash"
        ]
        context = {
            "schema_version": _CONTEXT_SCHEMA_VERSION,
            "context_id": f"context_{uuid4().hex}",
            "current_phase": phase,
            "parent_attempt_id": None,
            "phase_attempt_ids": {phase: attempt_id},
            "phase_authorization_ids": {
                phase: authorization_id,
            },
            "output_directory": str(output_directory),
            "readiness_path": str(readiness_file.resolve()),
            "readiness_sha256": _file_sha256(readiness_file),
            "expected_manifest_sha256": authorization[
                "expected_manifest_sha256"
            ],
            "ledger_path": str(ledger.resolve()),
            "allocated_ledger_revision": next_revision,
            "allocated_ledger_hash": allocation_revision[
                "revision_hash"
            ],
            "attempt_record_sha256": (
                _attempt_allocation_sha256(attempt)
            ),
        }
        if parent is not None:
            parent_ids = parent.get("phase_attempt_ids")
            parent_authorizations = parent.get(
                "phase_authorization_ids"
            )
            if (
                not isinstance(parent_ids, dict)
                or not isinstance(parent_authorizations, dict)
                or parent.get("expected_manifest_sha256")
                != context["expected_manifest_sha256"]
            ):
                raise AttemptLedgerError(
                    "parent attempt context is invalid"
                )
            context["parent_attempt_id"] = parent_ids[
                attempt_context_phase(parent)
            ]
            context["phase_attempt_ids"] = {
                **parent_ids,
                phase: attempt_id,
            }
            context["phase_authorization_ids"] = {
                **parent_authorizations,
                phase: authorization_id,
            }
            context["required_parent_summary"] = parent_summary
        attempt["context_sha256"] = sha256(
            _canonical_bytes(context)
        ).hexdigest()
        _write_immutable_json(context_path, context)
        try:
            _atomic_write_ledger(ledger, payload, binding=binding)
        except Exception:
            current = _read_ledger_unlocked(ledger, binding=binding)
            committed = [
                item
                for item in current["attempts"]
                if (
                    isinstance(item, dict)
                    and item.get("attempt_id") == attempt_id
                    and item.get("context_path") == str(context_path)
                    and item.get("context_sha256")
                    == attempt["context_sha256"]
                )
            ]
            if len(committed) == 1:
                _write_attempt_context_witness(
                    binding=binding,
                    attempt_id=attempt_id,
                    context=context,
                )
                return context_path
            _rollback_attempt_allocation(
                binding=binding,
                attempt_id=attempt_id,
                context=context,
                output_directory=output_directory,
                context_path=context_path,
            )
            raise
        _write_attempt_context_witness(
            binding=binding,
            attempt_id=attempt_id,
            context=context,
        )
        return context_path


def register_runtime_bound_attempt(
    path: str | Path,
    *,
    phase: Literal["bounded", "browser"],
    ledger_path: str | Path,
    readiness_path: str | Path,
    registration_id: str,
    runtime_identity_sha256: str,
    runtime_public_key: str,
    host: str,
    port: int,
) -> dict[str, object]:
    from tools.guide_gates.runtime_auth import (
        RuntimeProofError,
        validate_runtime_public_key,
    )

    if (
        phase not in {"bounded", "browser"}
        or re.fullmatch(r"runtime_[0-9a-f]{16,64}", registration_id)
        is None
        or not _is_sha256(runtime_identity_sha256)
    ):
        raise AttemptLedgerError("runtime registration is invalid")
    try:
        address = ipaddress.ip_address(host)
        public_key = validate_runtime_public_key(runtime_public_key)
    except (ValueError, RuntimeProofError) as exc:
        raise AttemptLedgerError(
            "runtime registration is invalid"
        ) from exc
    if (
        not address.is_loopback
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65535
    ):
        raise AttemptLedgerError("runtime registration is invalid")

    context_path = Path(path)
    context, context_sha256 = _read_attempt_context_once(context_path)
    readiness_file = Path(readiness_path)
    ledger = Path(ledger_path)
    _verify_current_readiness(
        readiness_path=readiness_file,
        ledger_path=ledger,
        expected_manifest_sha256=str(
            context.get("expected_manifest_sha256")
        ),
    )
    readiness_binding = _capture_readiness_binding(readiness_file)
    readiness_sha256 = readiness_binding[0]
    with _ledger_lock(ledger) as binding:
        _recover_orphan_temp(ledger, binding=binding)
        payload = _read_ledger_unlocked(ledger, binding=binding)
        _require_current_readiness_binding(
            readiness_path=readiness_file,
            binding=readiness_binding,
        )
        if (
            Path(str(context.get("readiness_path"))).resolve()
            != readiness_file.resolve()
            or context.get("readiness_sha256") != readiness_sha256
            or Path(str(context.get("ledger_path"))).resolve()
            != ledger.resolve()
        ):
            raise AttemptLedgerError(
                "runtime registration binding is invalid"
            )
        attempt = _attempt_for_context(
            payload,
            context_path=context_path,
            phase=phase,
        )
        _validate_context_allocation(
            payload=payload,
            context=context,
            context_path=context_path,
            context_sha256=context_sha256,
            attempt=attempt,
        )
        authorization = _authorization(
            payload,
            attempt["retry_authorization_id"],
        )
        registrations = attempt.setdefault(
            "runtime_registrations",
            [],
        )
        if not isinstance(registrations, list):
            raise AttemptLedgerError(
                "runtime registration history is invalid"
            )
        if any(
            isinstance(item, dict)
            and item.get("state") in {"registered", "consumed"}
            for item in registrations
        ):
            raise AttemptLedgerError(
                "attempt already has an active runtime registration"
            )
        if any(
            isinstance(item, dict)
            and item.get("registration_id") == registration_id
            for candidate in payload["attempts"]
            for item in (
                candidate.get("runtime_registrations", ())
                if isinstance(candidate, dict)
                else ()
            )
        ):
            raise AttemptLedgerError(
                "runtime registration ID already exists"
            )
        if (
            attempt.get("result") != "allocated"
            or authorization.get("state") != "allocated"
            or authorization.get("attempt_id")
            != attempt.get("attempt_id")
        ):
            raise AttemptLedgerError(
                "runtime registration requires an allocated attempt"
            )
        registration = {
            "schema_version": _RUNTIME_REGISTRATION_SCHEMA_VERSION,
            "registration_id": registration_id,
            "phase": phase,
            "attempt_id": attempt["attempt_id"],
            "attempt_context_sha256": context_sha256,
            "readiness_sha256": readiness_sha256,
            "allocated_ledger_revision": context[
                "allocated_ledger_revision"
            ],
            "allocated_ledger_hash": context[
                "allocated_ledger_hash"
            ],
            "runtime_identity_sha256": runtime_identity_sha256,
            "runtime_public_key": public_key,
            "host": address.compressed,
            "port": port,
            "state": "registered",
            "registered_at": _utc_now(),
            "aborted_at": None,
            "terminated_at": None,
        }
        registrations.append(registration)
        payload["revision"] += 1
        payload["circuit_state"] = _circuit_state(payload)
        _append_revision(
            payload,
            operation="runtime_registered",
            attempt_id=str(attempt["attempt_id"]),
            authorization_id=str(
                authorization["authorization_id"]
            ),
        )
        _atomic_write_ledger(ledger, payload, binding=binding)
        return deepcopy(registration)


def abort_runtime_bound_registration(
    path: str | Path,
    *,
    phase: Literal["bounded", "browser"],
    ledger_path: str | Path,
    registration_id: str,
) -> dict[str, object]:
    if (
        phase not in {"bounded", "browser"}
        or re.fullmatch(r"runtime_[0-9a-f]{16,64}", registration_id)
        is None
    ):
        raise AttemptLedgerError("runtime registration is invalid")
    context_path = Path(path)
    context, context_sha256 = _read_attempt_context_once(context_path)
    ledger = Path(ledger_path)
    with _ledger_lock(ledger) as binding:
        _recover_orphan_temp(ledger, binding=binding)
        locked_context, locked_context_sha256 = (
            _read_attempt_context_once(context_path)
        )
        if (
            locked_context != context
            or locked_context_sha256 != context_sha256
        ):
            raise AttemptLedgerError(
                "attempt context content mismatch"
            )
        payload = _read_ledger_unlocked(ledger, binding=binding)
        attempt = _attempt_for_context(
            payload,
            context_path=context_path,
            phase=phase,
        )
        _validate_context_allocation(
            payload=payload,
            context=context,
            context_path=context_path,
            context_sha256=context_sha256,
            attempt=attempt,
        )
        authorization = _authorization(
            payload,
            attempt["retry_authorization_id"],
        )
        registrations = attempt.get("runtime_registrations")
        matches = (
            [
                item
                for item in registrations
                if (
                    isinstance(item, dict)
                    and item.get("registration_id") == registration_id
                )
            ]
            if isinstance(registrations, list)
            else []
        )
        if (
            len(matches) != 1
            or matches[0].get("state") != "registered"
            or attempt.get("result") != "allocated"
            or authorization.get("state") != "allocated"
        ):
            raise AttemptLedgerError(
                "runtime registration is not abortable"
            )
        registration = matches[0]
        registration["state"] = "aborted"
        registration["aborted_at"] = _utc_now()
        payload["revision"] += 1
        payload["circuit_state"] = _circuit_state(payload)
        _append_revision(
            payload,
            operation="runtime_registration_aborted",
            attempt_id=str(attempt["attempt_id"]),
            authorization_id=str(
                authorization["authorization_id"]
            ),
        )
        _atomic_write_ledger(ledger, payload, binding=binding)
        return deepcopy(registration)


def _required_parent_summary(
    parent: Mapping[str, object],
    *,
    phase: str,
    result: str,
) -> dict[str, str]:
    if phase != "backend":
        raise AttemptLedgerError(
            "required parent summary phase is invalid"
        )
    if result not in {"passed", "failed"}:
        raise AttemptLedgerError(
            "required parent summary result is invalid"
        )
    output = Path(str(parent.get("output_directory"))).resolve()
    summary = (output / "real-backend/summary.json").resolve()
    if (
        output not in summary.parents
        or not summary.is_file()
        or summary.is_symlink()
    ):
        raise AttemptLedgerError(
            "required parent summary is missing"
        )
    payload = _load_json_object(
        summary,
        label="required parent summary",
    )
    if (
        payload.get("schema_version")
        != "guide-final-real-backend-summary-v1"
        or not isinstance(payload.get("passed"), bool)
    ):
        raise AttemptLedgerError(
            "required parent summary is invalid"
        )
    actual = "passed" if payload["passed"] else "failed"
    if actual != result:
        raise AttemptLedgerError(
            "required parent summary result mismatch"
        )
    if result == "passed":
        _validate_passed_backend_evidence(
            attempt_root=output,
            summary_path=summary,
            summary=payload,
        )
    return {
        "phase": phase,
        "result": result,
        "path": str(summary),
        "sha256": _file_sha256(summary),
    }


def _checksum_bundle(
    directory: Path,
    *,
    label: str,
    allow_additional: bool = False,
) -> dict[str, str]:
    checksum_path = directory / "SHA256SUMS"
    try:
        lines = checksum_path.read_text(encoding="ascii").splitlines()
    except OSError as exc:
        raise AttemptLedgerError(
            f"{label} evidence checksum index is missing"
        ) from exc
    indexed: dict[str, str] = {}
    for line in lines:
        digest, separator, relative = line.partition("  ")
        if (
            separator != "  "
            or not _is_sha256(digest)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or relative in indexed
        ):
            raise AttemptLedgerError(
                f"{label} evidence checksum index is invalid"
            )
        artifact = directory / relative
        if (
            not artifact.is_file()
            or artifact.is_symlink()
            or _file_sha256(artifact) != digest
        ):
            raise AttemptLedgerError(
                f"{label} evidence checksum mismatch"
            )
        indexed[relative] = digest
    required = {"results.jsonl", "summary.json"}
    if (
        not required <= set(indexed)
        or (not allow_additional and set(indexed) != required)
    ):
        raise AttemptLedgerError(
            f"{label} evidence checksum index is invalid"
        )
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path != checksum_path
    }
    if set(indexed) != actual:
        raise AttemptLedgerError(
            f"{label} evidence checksum index is incomplete"
        )
    return indexed


def _backend_sse_events(
    path: Path,
) -> tuple[SseEvent, ...]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AttemptLedgerError(
            "backend raw SSE evidence is invalid"
        ) from exc
    events: list[SseEvent] = []
    public_events: list[tuple[str, dict[str, object]]] = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        if not block:
            continue
        event_name: str | None = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                if event_name is not None:
                    raise AttemptLedgerError(
                        "backend raw SSE evidence is invalid"
                    )
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
            elif line.strip():
                raise AttemptLedgerError(
                    "backend raw SSE evidence is invalid"
                )
        if not event_name or not data_lines:
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
        try:
            event = _SSE_EVENT_ADAPTER.validate_json(
                json.dumps(
                    {
                        "event": event_name,
                        "data": _internal_event_payload(
                            event_name,
                            payload,
                        ),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                strict=True,
            )
        except ValidationError as exc:
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            ) from exc
        events.append(event)
        public_events.append((event_name, payload))
    if not events or not isinstance(events[0], StartEvent):
        raise AttemptLedgerError(
            "backend raw SSE evidence is invalid"
        )
    try:
        projected = materialize_guide_public_events(
            events,
            session_id=events[0].data.session_id,
        )
    except (GuidePublicEventError, GuideTerminalContractError) as exc:
        raise AttemptLedgerError(
            "backend raw SSE evidence is invalid"
        ) from exc
    if tuple(public_events) != projected:
        raise AttemptLedgerError(
            "backend raw SSE evidence is invalid"
        )
    return tuple(events)


def _internal_event_payload(
    event_name: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    if event_name == "stage":
        if set(payload) != {"message", "status", "stage"}:
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
        if payload.get("status") != "active":
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
        return {
            "stage": payload.get("stage"),
            "summary": payload.get("message"),
        }
    if event_name == "intent":
        required = {"intent", "entities", "scenario_intent", "guide"}
        if (
            not required <= set(payload)
            or set(payload) - required != {"category_profile"}
            and set(payload) != required
            or payload.get("entities") != {}
            or payload.get("scenario_intent") != payload.get("intent")
            or payload.get("guide") is not True
        ):
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
        internal = {"mode": payload.get("intent")}
        if "category_profile" in payload:
            internal["category_profile"] = payload["category_profile"]
        return internal
    if event_name == "decision_process":
        allowed = {
            "ordered_product_ids",
            "winner_status",
            "evidence_refs",
            "decision_process",
            "comparison_data",
            "suitability_data",
        }
        if not set(payload) <= allowed:
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
        return {
            key: payload[key]
            for key in (
                "ordered_product_ids",
                "winner_status",
                "evidence_refs",
                "comparison_data",
                "suitability_data",
            )
            if key in payload
        }
    if event_name == "answer_contract":
        if set(payload) != {
            "answer_contract",
            "winner_status",
            "product_count",
            "has_unknown_skin",
        }:
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
        answer = payload.get("answer_contract")
        if not isinstance(answer, dict) or any(
            payload.get(key) != answer.get(key)
            for key in (
                "winner_status",
                "product_count",
                "has_unknown_skin",
            )
        ):
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
        return dict(answer)
    if event_name == "products":
        if set(payload) != {"cards", "products"}:
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
        return {"cards": payload.get("cards")}
    if event_name == "message":
        if (
            set(payload) != {"content", "done"}
            or payload.get("done") is not False
        ):
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
        return {"content": payload.get("content")}
    if event_name == "error":
        if set(payload) != {"error", "message"}:
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
        return {
            "code": payload.get("error"),
            "message": payload.get("message"),
        }
    return dict(payload)


def _backend_sse_event_names(path: Path) -> tuple[str, ...]:
    return tuple(event.event for event in _backend_sse_events(path))


def _backend_sse_payloads_match(
    *,
    events: Sequence[SseEvent],
    row: Mapping[str, object],
) -> bool:
    presentations = [
        event.data
        for event in events
        if isinstance(event, PresentationContractEvent)
    ]
    clarifications = [
        event.data
        for event in events
        if isinstance(event, ClarifyEvent)
    ]
    if row.get("clarification") is True:
        if len(clarifications) != 1 or presentations:
            return False
        return (
            row.get("expected_responsibility") == "clarification"
            and row.get("actual_responsibility") == "clarification"
        )
    if len(presentations) != 1 or clarifications:
        return False
    presentation = presentations[0]
    return (
        presentation.responsibility.value
        == row.get("expected_responsibility")
        == row.get("actual_responsibility")
        and list(presentation.visible_product_ids)
        == row.get("visible_product_ids")
    )


def _validate_passed_backend_evidence(
    *,
    attempt_root: Path,
    summary_path: Path,
    summary: Mapping[str, object],
) -> None:
    canonical_fixture = _REPO_ROOT / _FINAL_FIXTURE_PATH
    required_hashes = (
        "fixture_sha256",
        "translation_results_sha256",
        "translation_summary_sha256",
        "translation_checksums_sha256",
        "results_sha256",
    )
    if (
        summary.get("fixture_path") != _FINAL_FIXTURE_PATH
        or summary.get("context_replay_mode")
        != "sealed_case_context"
        or summary.get("stateful_transition_count") != 0
        or any(not _is_sha256(summary.get(key)) for key in required_hashes)
        or any(
            type(summary.get(key)) is not int
            or summary.get(key) != expected
            for key, expected in _BACKEND_REQUIRED_COUNTS.items()
        )
        or any(
            type(summary.get(key)) is not int
            or summary.get(key) != 0
            for key in _BACKEND_ZERO_COUNTS
        )
        or type(summary.get("non_clarification_turn_count")) is not int
        or type(summary.get("clarification_turn_count")) is not int
        or type(summary.get("presentation_contract_count")) is not int
        or summary.get("non_clarification_turn_count")
        != summary.get("presentation_contract_count")
        or (
            int(summary.get("non_clarification_turn_count"))
            + int(summary.get("clarification_turn_count"))
            != 48
        )
    ):
        raise AttemptLedgerError("backend evidence is incomplete")
    if (
        not canonical_fixture.is_file()
        or canonical_fixture.is_symlink()
        or summary.get("fixture_sha256")
        != _file_sha256(canonical_fixture)
    ):
        raise AttemptLedgerError(
            "backend evidence canonical fixture binding is invalid"
        )

    backend_directory = summary_path.parent
    backend_index = _checksum_bundle(
        backend_directory,
        label="backend",
        allow_additional=True,
    )
    if (
        backend_index["results.jsonl"] != summary.get("results_sha256")
        or backend_index["summary.json"] != _file_sha256(summary_path)
    ):
        raise AttemptLedgerError("backend evidence checksum mismatch")
    try:
        backend_rows = [
            json.loads(line)
            for line in (
                backend_directory / "results.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise AttemptLedgerError(
            "backend evidence results are invalid"
        ) from exc
    try:
        fixture_rows = [
            json.loads(line)
            for line in canonical_fixture.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        expected_identities = tuple(
            (
                trajectory["trajectory_id"],
                turn["turn_id"],
            )
            for trajectory in fixture_rows
            for turn in trajectory["turns"]
        )
        expected_context_hashes = tuple(
            sha256(
                json.dumps(
                    turn["case"]["context"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            for trajectory in fixture_rows
            for turn in trajectory["turns"]
        )
        seed_image_rows = [
            json.loads(line)
            for line in (
                _REPO_ROOT / _SEED_IMAGE_ASSETS_PATH
            ).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        seed_image_sha256_by_product = {
            row["product_id"]: row["source_image_sha256"]
            for row in seed_image_rows
        }
        if (
            len(seed_image_sha256_by_product) != len(seed_image_rows)
            or any(
                type(row["product_id"]) is not int
                or row["product_id"] <= 0
                or not _is_sha256(row["source_image_sha256"])
                or not isinstance(row["relative_path"], str)
                or not (
                    asset_path := (
                        _REPO_ROOT / row["relative_path"]
                    ).resolve()
                ).is_file()
                or _REPO_ROOT not in asset_path.parents
                or asset_path.is_symlink()
                or _file_sha256(asset_path)
                != row["source_image_sha256"]
                for row in seed_image_rows
            )
        ):
            raise AttemptLedgerError(
                "canonical image asset index is invalid"
            )
        expected_image_bindings = tuple(
            (
                tuple(turn["image_product_ids"]),
                tuple(
                    seed_image_sha256_by_product[product_id]
                    for product_id in turn["image_product_ids"]
                ),
            )
            for trajectory in fixture_rows
            for turn in trajectory["turns"]
        )
        critical_trajectory_ids = {
            trajectory["trajectory_id"]
            for trajectory in fixture_rows
            if trajectory["critical"] is True
        }
    except (
        KeyError,
        OSError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        raise AttemptLedgerError(
            "canonical fixture identity index is invalid"
        ) from exc
    if (
        len(backend_rows) != 48
        or any(
            not isinstance(row, dict)
            for row in backend_rows
        )
    ):
        raise AttemptLedgerError(
            "backend evidence does not prove 48 passed turns"
        )
    identities = tuple(
        (row.get("trajectory_id"), row.get("turn_id"))
        for row in backend_rows
    )
    if (
        len(expected_identities) != 48
        or identities != expected_identities
        or len(set(identities)) != 48
    ):
        raise AttemptLedgerError(
            "backend evidence turn identity is invalid"
        )
    for row, expected_context_hash, expected_image_binding in zip(
        backend_rows,
        expected_context_hashes,
        expected_image_bindings,
        strict=True,
    ):
        clarification = row.get("clarification")
        presentation_count = row.get("presentation_contract_count")
        visible_product_ids = row.get("visible_product_ids")
        event_names = row.get("event_names")
        raw_sse_path = row.get("raw_sse_path")
        raw_sse_sha256 = row.get("raw_sse_sha256")
        image_product_ids = row.get("image_product_ids")
        image_asset_sha256s = row.get("image_asset_sha256s")
        sealed_context_hash = row.get("sealed_context_sha256")
        observed_context_hash = row.get("observed_context_sha256")
        if (
            not _is_sha256(sealed_context_hash)
            or not _is_sha256(observed_context_hash)
            or row.get("context_mismatch_count")
            != int(sealed_context_hash != observed_context_hash)
            or sealed_context_hash != observed_context_hash
        ):
            raise AttemptLedgerError(
                "backend evidence context hash binding is invalid"
            )
        if sealed_context_hash != expected_context_hash:
            raise AttemptLedgerError(
                "backend evidence canonical context hash is invalid"
            )
        if (
            set(row) != _BACKEND_TRACE_KEYS
            or row.get("completed") is not True
            or row.get("passed") is not True
            or type(clarification) is not bool
            or row.get("translation_injection_count") != 1
            or any(
                type(row.get(key)) is not int or row.get(key) != 0
                for key in _BACKEND_TRACE_ZERO_COUNTS
            )
            or type(presentation_count) is not int
            or presentation_count != (0 if clarification else 1)
            or not isinstance(row.get("expected_responsibility"), str)
            or not row.get("expected_responsibility")
            or row.get("actual_responsibility")
            != row.get("expected_responsibility")
            or not isinstance(visible_product_ids, list)
            or any(
                type(product_id) is not int or product_id <= 0
                for product_id in visible_product_ids
            )
            or len(visible_product_ids) != len(set(visible_product_ids))
            or not isinstance(event_names, list)
            or not event_names
            or any(not isinstance(name, str) for name in event_names)
            or raw_sse_path
            != (
                f"turns/{row.get('trajectory_id')}/"
                f"{row.get('turn_id')}/stream.sse"
            )
            or not _is_sha256(raw_sse_sha256)
            or not isinstance(image_product_ids, list)
            or tuple(image_product_ids) != expected_image_binding[0]
            or not isinstance(image_asset_sha256s, list)
            or tuple(image_asset_sha256s) != expected_image_binding[1]
            or event_names[0] != "start"
            or event_names[-1] != "end"
            or event_names.count("end") != 1
            or ("clarify" in event_names) != clarification
            or ("presentation_contract" in event_names)
            == clarification
        ):
            raise AttemptLedgerError(
                "backend evidence row is invalid"
            )
        raw_sse_file = backend_directory / str(raw_sse_path)
        if (
            backend_directory not in raw_sse_file.resolve().parents
            or not raw_sse_file.is_file()
            or raw_sse_file.is_symlink()
            or _file_sha256(raw_sse_file) != raw_sse_sha256
            or backend_index.get(str(raw_sse_path)) != raw_sse_sha256
        ):
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
        raw_sse_events = _backend_sse_events(raw_sse_file)
        if (
            tuple(event.event for event in raw_sse_events)
            != tuple(event_names)
            or not _backend_sse_payloads_match(
                events=raw_sse_events,
                row=row,
            )
        ):
            raise AttemptLedgerError(
                "backend raw SSE evidence is invalid"
            )
    if set(backend_index) != {
        "results.jsonl",
        "summary.json",
        *(str(row["raw_sse_path"]) for row in backend_rows),
    }:
        raise AttemptLedgerError(
            "backend raw SSE evidence index is invalid"
        )

    clarification_count = sum(
        row["clarification"] for row in backend_rows
    )
    non_clarification_count = len(backend_rows) - clarification_count
    presentation_count = sum(
        int(row["presentation_contract_count"])
        for row in backend_rows
    )
    passed_by_trajectory = {
        trajectory_id: all(
            row["passed"] is True
            for row in backend_rows
            if row["trajectory_id"] == trajectory_id
        )
        for trajectory_id, _ in expected_identities
    }
    derived_summary = {
        "trajectory_count": len({
            row["trajectory_id"] for row in backend_rows
        }),
        "critical_trajectory_count": len(critical_trajectory_ids),
        "critical_trajectory_passed": sum(
            passed_by_trajectory[trajectory_id]
            for trajectory_id in critical_trajectory_ids
        ),
        "expected_turn_count": len(expected_identities),
        "turn_count": len(backend_rows),
        "completed_turn_count": sum(
            row["completed"] for row in backend_rows
        ),
        "passed_turn_count": sum(
            row["passed"] for row in backend_rows
        ),
        "non_clarification_turn_count": non_clarification_count,
        "clarification_turn_count": clarification_count,
        "translation_injection_count": sum(
            int(row["translation_injection_count"])
            for row in backend_rows
        ),
        "presentation_contract_count": presentation_count,
        "wrong_presentation_count": abs(
            presentation_count - non_clarification_count
        ),
        "internal_public_language_count": sum(
            int(row["internal_language_count"])
            for row in backend_rows
        ),
        **{
            key: sum(int(row[key]) for row in backend_rows)
            for key in _BACKEND_TRACE_ZERO_COUNTS
            if key != "internal_public_language_count"
        },
    }
    if any(
        summary.get(key) != expected
        for key, expected in derived_summary.items()
    ):
        raise AttemptLedgerError(
            "backend evidence summary does not match rows"
        )

    translation_directory = attempt_root / "real-translation"
    translation_index = _checksum_bundle(
        translation_directory,
        label="translation",
    )
    translation_summary_path = translation_directory / "summary.json"
    translation_summary = _load_json_object(
        translation_summary_path,
        label="translation summary",
    )
    focused_path = attempt_root / "focused.json"
    if (
        translation_summary.get("schema_version")
        != "guide-final-real-translation-summary-v1"
        or translation_summary.get("passed") is not True
        or translation_summary.get("fixture_path") != _FINAL_FIXTURE_PATH
        or translation_summary.get("fixture_sha256")
        != summary.get("fixture_sha256")
        or translation_summary.get("focused_summary_sha256")
        != _file_sha256(focused_path)
        or translation_summary.get("results_sha256")
        != translation_index["results.jsonl"]
        or summary.get("translation_results_sha256")
        != translation_index["results.jsonl"]
        or summary.get("translation_summary_sha256")
        != translation_index["summary.json"]
        or summary.get("translation_checksums_sha256")
        != _file_sha256(translation_directory / "SHA256SUMS")
    ):
        raise AttemptLedgerError(
            "backend evidence translation binding is invalid"
        )


def _validate_required_parent_summary_binding(
    context: Mapping[str, object],
) -> None:
    binding = context.get("required_parent_summary")
    parent_attempt_id = context.get("parent_attempt_id")
    if parent_attempt_id is None:
        if binding is not None:
            raise AttemptLedgerError(
                "required parent summary binding is invalid"
            )
        return
    if not isinstance(binding, dict):
        raise AttemptLedgerError(
            "required parent summary binding is invalid"
        )
    verified = _required_parent_summary(
        {
            "output_directory": Path(str(binding.get("path"))).resolve()
            .parent.parent
        },
        phase=str(binding.get("phase")),
        result=str(binding.get("result")),
    )
    if verified != binding:
        raise AttemptLedgerError(
            "required parent summary binding changed"
        )


def read_attempt_context(
    path: str | Path,
    *,
    ledger_path: str | Path,
    readiness_path: str | Path,
) -> dict[str, Any]:
    context_path = Path(path)
    context, context_sha256 = _read_attempt_context_once(context_path)
    if context.get("schema_version") != _CONTEXT_SCHEMA_VERSION:
        raise AttemptLedgerError("attempt context is invalid")
    if Path(str(context.get("ledger_path"))).resolve() != Path(
        ledger_path
    ).resolve():
        raise AttemptLedgerError("attempt context ledger mismatch")
    if Path(str(context.get("readiness_path"))).resolve() != Path(
        readiness_path
    ).resolve():
        raise AttemptLedgerError("attempt context readiness mismatch")
    payload = read_ledger(ledger_path)
    attempt_ids = context.get("phase_attempt_ids")
    if not isinstance(attempt_ids, dict) or not attempt_ids:
        raise AttemptLedgerError("attempt context is invalid")
    for attempt_id in attempt_ids.values():
        matches = [
            attempt
            for attempt in payload["attempts"]
            if isinstance(attempt, dict)
            and attempt.get("attempt_id") == attempt_id
        ]
        if len(matches) != 1:
            raise AttemptLedgerError(
                "attempt context allocation is invalid"
            )
    current_phase = attempt_context_phase(context)
    current_attempt_id = attempt_ids[current_phase]
    current_attempt = next(
        attempt
        for attempt in payload["attempts"]
        if attempt.get("attempt_id") == current_attempt_id
    )
    _validate_context_allocation(
        payload=payload,
        context=context,
        context_path=context_path,
        context_sha256=context_sha256,
        attempt=current_attempt,
    )
    return context


def attempt_context_phase(
    context: Mapping[str, object],
) -> Phase:
    phase = context.get("current_phase")
    phase_attempt_ids = context.get("phase_attempt_ids")
    if (
        phase not in _PHASES
        or not isinstance(phase_attempt_ids, dict)
        or phase not in phase_attempt_ids
        or not isinstance(phase_attempt_ids[phase], str)
    ):
        raise AttemptLedgerError(
            "attempt context current phase is invalid"
        )
    return phase


def _attempt_for_context(
    payload: dict[str, Any],
    *,
    context_path: Path,
    phase: Phase,
) -> dict[str, Any]:
    matches = [
        attempt
        for attempt in payload["attempts"]
        if isinstance(attempt, dict)
        and attempt.get("trajectory_set") == phase
        and attempt.get("context_path") == str(context_path.resolve())
    ]
    if len(matches) != 1:
        raise AttemptLedgerError("attempt context allocation is invalid")
    return matches[0]


def _validate_context_allocation(
    *,
    payload: dict[str, Any],
    context: dict[str, Any],
    context_path: Path,
    context_sha256: str,
    attempt: dict[str, Any],
) -> None:
    if attempt.get("context_sha256") != context_sha256:
        raise AttemptLedgerError("attempt context content mismatch")
    if (
        attempt.get("context_path") != str(context_path.resolve())
        or context.get("attempt_record_sha256")
        != _attempt_allocation_sha256(attempt)
        or attempt.get("trajectory_set")
        != attempt_context_phase(context)
        or not _is_sha256(context.get("expected_manifest_sha256"))
        or attempt.get("expected_manifest_sha256")
        != context.get("expected_manifest_sha256")
        or context["phase_attempt_ids"].get(
            attempt_context_phase(context)
        )
        != attempt.get("attempt_id")
    ):
        raise AttemptLedgerError(
            "attempt context allocation is invalid"
        )
    _validate_required_parent_summary_binding(context)
    allocated_revision = context.get("allocated_ledger_revision")
    allocated_hash = context.get("allocated_ledger_hash")
    allocation_matches = [
        entry
        for entry in payload["revision_chain"]
        if (
            entry.get("revision") == allocated_revision
            and entry.get("revision_hash") == allocated_hash
        )
    ]
    if (
        not isinstance(allocated_revision, int)
        or isinstance(allocated_revision, bool)
        or allocated_revision > payload["revision"]
        or not _is_sha256(allocated_hash)
        or len(allocation_matches) != 1
        or allocation_matches[0].get("operation")
        != "attempt_allocated"
        or allocation_matches[0].get("attempt_id")
        != attempt.get("attempt_id")
        or attempt.get("allocated_ledger_revision")
        != allocated_revision
        or attempt.get("allocated_ledger_hash") != allocated_hash
    ):
        raise AttemptLedgerError(
            "attempt context ledger revision is invalid"
        )


def _consume_attempt_context_locked(
    path: str | Path,
    *,
    phase: Phase,
    ledger_path: str | Path,
    readiness_path: str | Path,
    runtime_binding: Mapping[str, object] | None,
    loaded_context: tuple[dict[str, Any], str] | None = None,
) -> tuple[dict[str, Any], dict[str, object] | None, str | None]:
    context_path = Path(path)
    context, context_sha256 = (
        _read_attempt_context_once(context_path)
        if loaded_context is None
        else loaded_context
    )
    readiness_file = Path(readiness_path)
    ledger = Path(ledger_path)
    _verify_current_readiness(
        readiness_path=readiness_file,
        ledger_path=ledger,
        expected_manifest_sha256=str(
            context.get("expected_manifest_sha256")
        ),
    )
    readiness_binding = _capture_readiness_binding(readiness_file)
    with _ledger_lock(ledger) as binding:
        _recover_orphan_temp(ledger, binding=binding)
        locked_context, locked_context_sha256 = (
            _read_attempt_context_once(context_path)
        )
        if (
            locked_context != context
            or locked_context_sha256 != context_sha256
        ):
            raise AttemptLedgerError(
                "attempt context content mismatch"
            )
        payload = _read_ledger_unlocked(ledger, binding=binding)
        _require_current_readiness_binding(
            readiness_path=readiness_file,
            binding=readiness_binding,
        )
        if (
            Path(str(context.get("readiness_path"))).resolve()
            != readiness_file.resolve()
            or Path(str(context.get("ledger_path"))).resolve()
            != ledger.resolve()
        ):
            raise AttemptLedgerError(
                "attempt context allocation is invalid"
            )
        attempt = _attempt_for_context(
            payload,
            context_path=context_path,
            phase=phase,
        )
        _validate_context_allocation(
            payload=payload,
            context=context,
            context_path=context_path,
            context_sha256=context_sha256,
            attempt=attempt,
        )
        authorization = _authorization(
            payload,
            attempt["retry_authorization_id"],
        )
        plan_revision = attempt.get("plan_revision")
        if (
            not isinstance(plan_revision, str)
            or not plan_revision
            or any(
                count >= 2
                for count in _failure_counts(
                    payload,
                    plan_revision=plan_revision,
                ).values()
            )
        ):
            raise AttemptLedgerError("smoke circuit is open")
        active_authorizations = [
            item
            for item in payload["authorizations"]
            if (
                isinstance(item, dict)
                and item.get("plan_revision") == plan_revision
                and item.get("state") in {"allocated", "consumed"}
            )
        ]
        if (
            len(active_authorizations) != 1
            or active_authorizations[0].get("authorization_id")
            != authorization.get("authorization_id")
        ):
            raise AttemptLedgerError(
                "plan revision has conflicting active authorization"
            )
        if (
            authorization.get("state") == "consumed"
            or attempt.get("result") == "consumed"
        ):
            raise AttemptLedgerError("authorization already consumed")
        if (
            authorization.get("state") != "allocated"
            or attempt.get("result") != "allocated"
        ):
            raise AttemptLedgerError("authorization is not consumable")
        if (
            authorization.get("readiness_sha256")
            != readiness_binding[0]
            or context.get("readiness_sha256")
            != readiness_binding[0]
        ):
            raise AttemptLedgerError("readiness changed after allocation")
        runtime_attestation: dict[str, object] | None = None
        runtime_attestation_sha256: str | None = None
        if phase in {"bounded", "browser"}:
            if not isinstance(runtime_binding, Mapping):
                raise AttemptLedgerError(
                    "runtime-bound attempt requires live runtime attestation"
                )
            identity_path = runtime_binding.get("identity_path")
            identity_bytes = runtime_binding.get("identity_bytes")
            identity = runtime_binding.get("identity")
            host = runtime_binding.get("host")
            port = runtime_binding.get("port")
            normalized_base_url = runtime_binding.get(
                "normalized_base_url"
            )
            runtime_identity_sha256 = runtime_binding.get(
                "runtime_identity_sha256"
            )
            if (
                not isinstance(identity_path, Path)
                or not isinstance(identity_bytes, bytes)
                or not isinstance(identity, dict)
                or not isinstance(host, str)
                or type(port) is not int
                or not isinstance(normalized_base_url, str)
                or not _is_sha256(runtime_identity_sha256)
                or identity_path.read_bytes() != identity_bytes
                or identity.get("attempt_id") != attempt.get("attempt_id")
            ):
                raise AttemptLedgerError(
                    "bound runtime identity changed before ledger consumption"
                )
            registration_id = identity.get(
                "runtime_registration_id"
            )
            registrations = attempt.get("runtime_registrations")
            matching_registrations = (
                [
                    item
                    for item in registrations
                    if (
                        isinstance(item, dict)
                        and item.get("registration_id")
                        == registration_id
                    )
                ]
                if isinstance(registrations, list)
                else []
            )
            if len(matching_registrations) != 1:
                raise AttemptLedgerError(
                    "bound runtime registration is invalid"
                )
            registration = matching_registrations[0]
            if (
                registration.get("schema_version")
                != _RUNTIME_REGISTRATION_SCHEMA_VERSION
                or registration.get("state") != "registered"
                or registration.get("phase") != phase
                or registration.get("attempt_id")
                != attempt.get("attempt_id")
                or registration.get("attempt_context_sha256")
                != context_sha256
                or registration.get("readiness_sha256")
                != readiness_binding[0]
                or registration.get("allocated_ledger_revision")
                != context.get("allocated_ledger_revision")
                or registration.get("allocated_ledger_hash")
                != context.get("allocated_ledger_hash")
                or registration.get("runtime_identity_sha256")
                != runtime_identity_sha256
                or registration.get("runtime_public_key")
                != identity.get("runtime_public_key")
                or registration.get("host") != host
                or registration.get("port") != port
            ):
                raise AttemptLedgerError(
                    "bound runtime registration is invalid"
                )
            proof_request = {
                "schema_version": PROOF_REQUEST_SCHEMA,
                "registration_id": registration_id,
                "phase": phase,
                "attempt_id": attempt["attempt_id"],
                "attempt_context_sha256": context_sha256,
                "readiness_sha256": readiness_binding[0],
                "allocated_ledger_revision": context[
                    "allocated_ledger_revision"
                ],
                "allocated_ledger_hash": context[
                    "allocated_ledger_hash"
                ],
                "runtime_identity_sha256": runtime_identity_sha256,
                "verifier_nonce": secrets.token_hex(32),
            }
            proof = _request_live_runtime_proof(
                host=host,
                port=port,
                request=proof_request,
            )
            try:
                verified_proof = verify_runtime_proof(
                    proof=proof,
                    expected_request=proof_request,
                    expected_public_key=str(
                        registration["runtime_public_key"]
                    ),
                )
            except RuntimeProofError as exc:
                raise AttemptLedgerError(
                    "bound runtime proof is invalid"
                ) from exc
            runtime_proof_sha256 = sha256(
                _canonical_bytes(verified_proof)
            ).hexdigest()
            process_identity = identity["process_identity"]
            runtime_attestation = {
                "schema_version": _RUNTIME_ATTESTATION_SCHEMA_VERSION,
                "phase": phase,
                "attempt_id": attempt["attempt_id"],
                "attempt_context_sha256": context_sha256,
                "runtime_registration_id": registration_id,
                "runtime_identity_path": str(identity_path),
                "runtime_identity_sha256": runtime_identity_sha256,
                "runtime_public_key": registration[
                    "runtime_public_key"
                ],
                "runtime_process_id": process_identity["pid"],
                "base_url": normalized_base_url,
                "runtime_proof_sha256": runtime_proof_sha256,
            }
            runtime_attestation_sha256 = sha256(
                _canonical_bytes(runtime_attestation)
            ).hexdigest()
            attempt["runtime_proof"] = deepcopy(verified_proof)
            attempt["runtime_proof_sha256"] = runtime_proof_sha256
            attempt["runtime_attestation"] = deepcopy(
                runtime_attestation
            )
            attempt["runtime_attestation_sha256"] = (
                runtime_attestation_sha256
            )
            registration["state"] = "consumed"
            registration["consumed_at"] = _utc_now()
        elif runtime_binding is not None:
            raise AttemptLedgerError(
                "translation attempt forbids runtime attestation"
            )
        authorization["state"] = "consumed"
        authorization["consumed_at"] = _utc_now()
        attempt["result"] = "consumed"
        payload["revision"] += 1
        payload["circuit_state"] = _circuit_state(payload)
        _append_revision(
            payload,
            operation="authorization_consumed",
            attempt_id=str(attempt["attempt_id"]),
            authorization_id=str(
                authorization["authorization_id"]
            ),
            source_sha256=runtime_attestation_sha256,
        )
        final_context, final_context_sha256 = (
            _read_attempt_context_once(context_path)
        )
        if (
            final_context != context
            or final_context_sha256 != context_sha256
        ):
            raise AttemptLedgerError(
                "attempt context content mismatch"
            )
        _require_current_readiness_binding(
            readiness_path=readiness_file,
            binding=readiness_binding,
        )
        if phase in {"bounded", "browser"}:
            final_identity_path = runtime_binding.get("identity_path")
            final_identity_bytes = runtime_binding.get("identity_bytes")
            if (
                not isinstance(final_identity_path, Path)
                or not isinstance(final_identity_bytes, bytes)
                or final_identity_path.read_bytes()
                != final_identity_bytes
            ):
                raise AttemptLedgerError(
                    "bound runtime identity changed before ledger consumption"
                )
        _atomic_write_ledger(ledger, payload, binding=binding)
    return context, runtime_attestation, runtime_attestation_sha256


def consume_attempt_context(
    path: str | Path,
    *,
    phase: Phase,
    ledger_path: str | Path,
    readiness_path: str | Path,
) -> dict[str, Any]:
    context, _, _ = _consume_attempt_context_locked(
        path,
        phase=phase,
        ledger_path=ledger_path,
        readiness_path=readiness_path,
        runtime_binding=None,
    )
    return context


def consume_runtime_bound_attempt(
    path: str | Path,
    *,
    phase: Literal["bounded", "browser"],
    ledger_path: str | Path,
    readiness_path: str | Path,
    base_url: str,
) -> dict[str, str]:
    if phase not in {"bounded", "browser"}:
        raise AttemptLedgerError(
            "runtime-bound attempt phase is invalid"
        )
    context_path = Path(path).resolve()
    context, context_sha256 = _read_attempt_context_once(context_path)
    phase_attempt_ids = context.get("phase_attempt_ids")
    if (
        not isinstance(phase_attempt_ids, dict)
        or not isinstance(phase_attempt_ids.get(phase), str)
    ):
        raise AttemptLedgerError("attempt context phase is invalid")
    attempt_id = str(phase_attempt_ids[phase])
    host, port, normalized_base_url = _bound_runtime_endpoint(base_url)
    output_directory = Path(
        str(context.get("output_directory"))
    ).resolve()
    identity_entry = output_directory / _RUNTIME_IDENTITY_FILENAME
    if (
        not output_directory.is_dir()
        or output_directory.is_symlink()
        or identity_entry.is_symlink()
        or not identity_entry.is_file()
    ):
        raise AttemptLedgerError(
            "bound runtime identity is invalid"
        )
    identity_path = identity_entry.resolve()
    if output_directory not in identity_path.parents:
        raise AttemptLedgerError(
            "bound runtime identity is invalid"
        )
    identity = _verify_live_bound_runtime_identity(
        identity_path=identity_path,
        attempt_context=context_path,
        expected_host=host,
        expected_port=port,
    )
    try:
        identity_bytes = identity_path.read_bytes()
    except OSError as exc:
        raise AttemptLedgerError(
            "bound runtime identity is invalid"
        ) from exc
    runtime_identity_sha256 = sha256(identity_bytes).hexdigest()
    process_identity = identity.get("process_identity")
    if (
        identity != _load_json_object(
            identity_path,
            label="bound runtime identity",
        )
        or identity.get("schema_version")
        != "guide-bound-runtime-identity-v1"
        or identity.get("phase") != phase
        or identity.get("attempt_id") != attempt_id
        or identity.get("attempt_context_path") != str(context_path)
        or identity.get("attempt_context_sha256")
        != context_sha256
        or identity.get("readiness_sha256")
        != context.get("readiness_sha256")
        or identity.get("ledger_path")
        != str(Path(ledger_path).resolve())
        or identity.get("allocated_ledger_revision")
        != context.get("allocated_ledger_revision")
        or identity.get("allocated_ledger_hash")
        != context.get("allocated_ledger_hash")
        or re.fullmatch(
            r"runtime_[0-9a-f]{16,64}",
            str(identity.get("runtime_registration_id")),
        )
        is None
        or not isinstance(identity.get("runtime_public_key"), str)
        or identity.get("host") != host
        or identity.get("port") != port
        or not isinstance(process_identity, dict)
        or type(process_identity.get("pid")) is not int
        or process_identity["pid"] <= 0
    ):
        raise AttemptLedgerError(
            "bound runtime identity is invalid"
        )

    _, attestation, attestation_sha256 = (
        _consume_attempt_context_locked(
            context_path,
            phase=phase,
            ledger_path=ledger_path,
            readiness_path=readiness_path,
            runtime_binding={
                "identity_path": identity_path,
                "identity_bytes": identity_bytes,
                "identity": identity,
                "host": host,
                "port": port,
                "normalized_base_url": normalized_base_url,
                "runtime_identity_sha256": runtime_identity_sha256,
            },
            loaded_context=(context, context_sha256),
        )
    )
    if (
        attestation is None
        or not _is_sha256(attestation_sha256)
    ):
        raise AttemptLedgerError(
            "bound runtime attestation was not recorded"
        )
    return {
        "runtime_identity_sha256": str(
            attestation["runtime_identity_sha256"]
        ),
        "runtime_proof_sha256": str(attestation["runtime_proof_sha256"]),
        "runtime_attestation_sha256": str(attestation_sha256),
    }


def _validate_passed_bounded_browser_evidence(
    output_directory: object,
) -> None:
    from tools.guide_gates.run_mainline_contract_browser_audit import (
        AuditBundleError,
        validate_completed_bounded_browser_evidence,
    )

    try:
        validate_completed_bounded_browser_evidence(
            Path(str(output_directory))
        )
    except (AuditBundleError, OSError, ValueError) as exc:
        raise AttemptLedgerError(
            "bounded browser evidence is invalid"
        ) from exc


def validate_runtime_bound_attempt_attestation(
    *,
    context_path: str | Path,
    context: Mapping[str, object],
    context_sha256: str | None = None,
    attempt: Mapping[str, object],
    ledger: Mapping[str, object],
    require_browser_summary: bool,
) -> dict[str, object]:
    resolved_context_path = Path(context_path).resolve()
    if context_sha256 is None:
        current_context, context_sha256 = (
            _read_attempt_context_once(resolved_context_path)
        )
        if current_context != dict(context):
            raise AttemptLedgerError(
                "runtime attestation context is invalid"
            )
    elif not _is_sha256(context_sha256):
        raise AttemptLedgerError(
            "runtime attestation context is invalid"
        )
    phase = attempt.get("trajectory_set")
    attempt_id = attempt.get("attempt_id")
    authorization_id = attempt.get("retry_authorization_id")
    output_directory = Path(
        str(context.get("output_directory"))
    ).resolve()
    identity_entry = output_directory / _RUNTIME_IDENTITY_FILENAME
    identity_path = identity_entry.resolve()
    attestation = attempt.get("runtime_attestation")
    attestation_sha256 = attempt.get("runtime_attestation_sha256")
    expected_keys = {
        "schema_version",
        "phase",
        "attempt_id",
        "attempt_context_sha256",
        "runtime_registration_id",
        "runtime_identity_path",
        "runtime_identity_sha256",
        "runtime_public_key",
        "runtime_process_id",
        "base_url",
        "runtime_proof_sha256",
    }
    runtime_proof = attempt.get("runtime_proof")
    runtime_proof_sha256 = attempt.get("runtime_proof_sha256")
    registrations = attempt.get("runtime_registrations")
    registration_matches = (
        [
            item
            for item in registrations
            if (
                isinstance(item, dict)
                and item.get("registration_id")
                == attestation.get("runtime_registration_id")
            )
        ]
        if isinstance(registrations, list)
        and isinstance(attestation, dict)
        else []
    )
    revision_chain = ledger.get("revision_chain")
    if (
        phase not in {"bounded", "browser"}
        or not isinstance(attempt_id, str)
        or not isinstance(authorization_id, str)
        or not isinstance(attestation, dict)
        or set(attestation) != expected_keys
        or not isinstance(runtime_proof, dict)
        or not _is_sha256(runtime_proof_sha256)
        or runtime_proof_sha256
        != sha256(_canonical_bytes(runtime_proof)).hexdigest()
        or len(registration_matches) != 1
        or not _is_sha256(attestation_sha256)
        or attestation_sha256
        != sha256(_canonical_bytes(attestation)).hexdigest()
        or not isinstance(revision_chain, list)
    ):
        raise AttemptLedgerError(
            "runtime attestation is invalid"
        )
    consumed_revisions = [
        entry
        for entry in revision_chain
        if (
            isinstance(entry, dict)
            and entry.get("operation") == "authorization_consumed"
            and entry.get("attempt_id") == attempt_id
            and entry.get("authorization_id") == authorization_id
            and entry.get("source_sha256") == attestation_sha256
        )
    ]
    if len(consumed_revisions) != 1:
        raise AttemptLedgerError(
            "runtime attestation hash chain is invalid"
        )
    if (
        not output_directory.is_dir()
        or output_directory.is_symlink()
        or identity_entry.is_symlink()
        or not identity_entry.is_file()
        or output_directory not in identity_path.parents
    ):
        raise AttemptLedgerError(
            "runtime attestation identity is invalid"
        )
    identity = _load_json_object(
        identity_path,
        label="bound runtime identity",
    )
    process_identity = identity.get("process_identity")
    registration = registration_matches[0]
    try:
        host, port, normalized_base_url = _bound_runtime_endpoint(
            str(attestation.get("base_url"))
        )
        identity_bytes = identity_path.read_bytes()
    except OSError as exc:
        raise AttemptLedgerError(
            "runtime attestation identity is invalid"
        ) from exc
    if (
        identity_bytes != _canonical_bytes(identity)
        or attestation.get("schema_version")
        != _RUNTIME_ATTESTATION_SCHEMA_VERSION
        or attestation.get("phase") != phase
        or attestation.get("attempt_id") != attempt_id
        or attestation.get("attempt_context_sha256")
        != context_sha256
        or attestation.get("runtime_identity_path")
        != str(identity_path)
        or attestation.get("runtime_identity_sha256")
        != sha256(identity_bytes).hexdigest()
        or attestation.get("runtime_registration_id")
        != registration.get("registration_id")
        or attestation.get("runtime_public_key")
        != registration.get("runtime_public_key")
        or attestation.get("runtime_proof_sha256")
        != runtime_proof_sha256
        or registration.get("schema_version")
        != _RUNTIME_REGISTRATION_SCHEMA_VERSION
        or registration.get("state") not in {"consumed", "terminated"}
        or registration.get("phase") != phase
        or registration.get("attempt_id") != attempt_id
        or registration.get("attempt_context_sha256")
        != context_sha256
        or registration.get("readiness_sha256")
        != context.get("readiness_sha256")
        or registration.get("allocated_ledger_revision")
        != context.get("allocated_ledger_revision")
        or registration.get("allocated_ledger_hash")
        != context.get("allocated_ledger_hash")
        or registration.get("runtime_identity_sha256")
        != attestation.get("runtime_identity_sha256")
        or not isinstance(process_identity, dict)
        or type(process_identity.get("pid")) is not int
        or process_identity["pid"] <= 0
        or attestation.get("runtime_process_id")
        != process_identity["pid"]
        or identity.get("schema_version")
        != "guide-bound-runtime-identity-v1"
        or identity.get("phase") != phase
        or identity.get("attempt_id") != attempt_id
        or identity.get("attempt_context_path")
        != str(resolved_context_path)
        or identity.get("attempt_context_sha256")
        != context_sha256
        or identity.get("readiness_sha256")
        != context.get("readiness_sha256")
        or identity.get("ledger_path")
        != str(Path(str(context.get("ledger_path"))).resolve())
        or identity.get("allocated_ledger_revision")
        != context.get("allocated_ledger_revision")
        or identity.get("allocated_ledger_hash")
        != context.get("allocated_ledger_hash")
        or identity.get("runtime_registration_id")
        != registration.get("registration_id")
        or identity.get("runtime_public_key")
        != registration.get("runtime_public_key")
        or identity.get("host") != host
        or identity.get("port") != port
        or attestation.get("base_url") != normalized_base_url
    ):
        raise AttemptLedgerError(
            "runtime attestation identity is invalid"
        )
    proof_request = {
        "schema_version": PROOF_REQUEST_SCHEMA,
        "registration_id": registration["registration_id"],
        "phase": phase,
        "attempt_id": attempt_id,
        "attempt_context_sha256": context_sha256,
        "readiness_sha256": context["readiness_sha256"],
        "allocated_ledger_revision": context[
            "allocated_ledger_revision"
        ],
        "allocated_ledger_hash": context["allocated_ledger_hash"],
        "runtime_identity_sha256": attestation[
            "runtime_identity_sha256"
        ],
        "verifier_nonce": runtime_proof.get("verifier_nonce"),
    }
    try:
        verify_runtime_proof(
            proof=runtime_proof,
            expected_request=proof_request,
            expected_public_key=str(registration["runtime_public_key"]),
        )
    except RuntimeProofError as exc:
        raise AttemptLedgerError(
            "runtime attestation proof is invalid"
        ) from exc
    if require_browser_summary:
        if phase == "bounded":
            summary_paths = tuple(
                sorted(output_directory.glob("browser-*/summary.json"))
            )
            if len(summary_paths) != 1:
                raise AttemptLedgerError(
                    "runtime attestation browser summary is invalid"
                )
            summary_path = summary_paths[0]
        else:
            summary_path = output_directory / (
                "mainline-browser/summary.json"
            )
        if not summary_path.is_file() or summary_path.is_symlink():
            raise AttemptLedgerError(
                "runtime attestation browser summary is invalid"
            )
        summary = _load_json_object(
            summary_path,
            label="runtime-bound browser summary",
        )
        if (
            summary.get("runtime_identity_sha256")
            != attestation["runtime_identity_sha256"]
            or summary.get("runtime_proof_sha256")
            != attestation["runtime_proof_sha256"]
            or summary.get("runtime_attestation_sha256")
            != attestation_sha256
        ):
            raise AttemptLedgerError(
                "runtime attestation browser binding is invalid"
            )
    return deepcopy(attestation)


def _read_runtime_authority_ledger_unlocked(
    path: Path,
    *,
    binding: _BoundLedgerPath,
) -> dict[str, Any]:
    canonical = _canonical_ledger_path(path)
    content = _read_regular_file_once(
        canonical,
        label="canonical ledger",
        binding=binding,
    )
    return _validate_ledger(
        _decode_json_object_bytes(content, label="canonical ledger"),
        expected_path=canonical,
    )


def _validate_runtime_request_context_allocation(
    *,
    payload: dict[str, Any],
    context: dict[str, Any],
    context_path: Path,
    context_sha256: str,
    attempt: dict[str, Any],
) -> None:
    phase = attempt_context_phase(context)
    allocated_revision = context.get("allocated_ledger_revision")
    allocated_hash = context.get("allocated_ledger_hash")
    allocation_matches = [
        entry
        for entry in payload["revision_chain"]
        if (
            entry.get("revision") == allocated_revision
            and entry.get("revision_hash") == allocated_hash
        )
    ]
    if (
        attempt.get("context_sha256") != context_sha256
        or attempt.get("context_path") != str(context_path.resolve())
        or context.get("attempt_record_sha256")
        != _attempt_allocation_sha256(attempt)
        or attempt.get("trajectory_set") != phase
        or not _is_sha256(context.get("expected_manifest_sha256"))
        or attempt.get("expected_manifest_sha256")
        != context.get("expected_manifest_sha256")
        or context["phase_attempt_ids"].get(phase)
        != attempt.get("attempt_id")
        or not isinstance(allocated_revision, int)
        or isinstance(allocated_revision, bool)
        or allocated_revision > payload["revision"]
        or not _is_sha256(allocated_hash)
        or len(allocation_matches) != 1
        or allocation_matches[0].get("operation")
        != "attempt_allocated"
        or allocation_matches[0].get("attempt_id")
        != attempt.get("attempt_id")
        or attempt.get("allocated_ledger_revision")
        != allocated_revision
        or attempt.get("allocated_ledger_hash") != allocated_hash
    ):
        raise AttemptLedgerError(
            "runtime request context allocation is invalid"
        )


def validate_runtime_request_authority(
    context_path: str | Path,
    *,
    phase: Literal["bounded", "browser"],
    attempt_id: str,
) -> None:
    if phase not in {"bounded", "browser"}:
        raise AttemptLedgerError(
            "runtime request phase is invalid"
        )
    resolved_context_path = Path(context_path).resolve()
    context, context_sha256 = _read_attempt_context_once(
        resolved_context_path
    )
    ledger = Path(str(context.get("ledger_path")))
    readiness_file = Path(str(context.get("readiness_path")))
    readiness_bytes = _read_regular_file_once(
        readiness_file,
        label="readiness",
    )
    readiness_sha256 = sha256(readiness_bytes).hexdigest()
    readiness = _decode_json_object_bytes(
        readiness_bytes,
        label="readiness",
    )
    phase_attempt_ids = context.get("phase_attempt_ids")
    if (
        context.get("current_phase") != phase
        or not isinstance(phase_attempt_ids, dict)
        or phase_attempt_ids.get(phase) != attempt_id
        or context.get("readiness_sha256") != readiness_sha256
        or readiness.get("ledger_path")
        != str(_canonical_ledger_path(ledger))
        or readiness.get("reviewed_candidate_manifest_sha256")
        != context.get("expected_manifest_sha256")
        or not isinstance(readiness.get("plan_revision"), str)
    ):
        raise AttemptLedgerError(
            "runtime request readiness binding is invalid"
        )
    with _ledger_lock(ledger, shared=True) as binding:
        locked_context, locked_context_sha256 = (
            _read_attempt_context_once(resolved_context_path)
        )
        if (
            locked_context != context
            or locked_context_sha256 != context_sha256
        ):
            raise AttemptLedgerError(
                "attempt context content mismatch"
            )
        if (
            _read_regular_file_once(
                readiness_file,
                label="readiness",
            )
            != readiness_bytes
        ):
            raise AttemptLedgerError(
                "runtime request readiness binding is invalid"
            )
        payload = _read_runtime_authority_ledger_unlocked(
            ledger,
            binding=binding,
        )
        attempts = [
            item
            for item in payload["attempts"]
            if (
                isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
                and item.get("trajectory_set") == phase
            )
        ]
        if len(attempts) != 1:
            raise AttemptLedgerError(
                "runtime request attempt is invalid"
            )
        attempt = attempts[0]
        _validate_runtime_request_context_allocation(
            payload=payload,
            context=context,
            context_path=resolved_context_path,
            context_sha256=context_sha256,
            attempt=attempt,
        )
        authorization = _authorization(
            payload,
            attempt["retry_authorization_id"],
        )
        if (
            attempt.get("result") != "consumed"
            or authorization.get("state") != "consumed"
            or authorization.get("attempt_id") != attempt_id
            or authorization.get("readiness_sha256")
            != readiness_sha256
            or context.get("readiness_sha256")
            != readiness_sha256
            or attempt.get("plan_revision")
            != readiness.get("plan_revision")
        ):
            raise AttemptLedgerError(
                "runtime request authorization is invalid"
            )
        validate_runtime_bound_attempt_attestation(
            context_path=resolved_context_path,
            context=context,
            context_sha256=context_sha256,
            attempt=attempt,
            ledger=payload,
            require_browser_summary=False,
        )
        final_context, final_context_sha256 = (
            _read_attempt_context_once(resolved_context_path)
        )
        if (
            final_context != context
            or final_context_sha256 != context_sha256
        ):
            raise AttemptLedgerError(
                "attempt context content mismatch"
            )
        if (
            _read_regular_file_once(
                readiness_file,
                label="readiness",
            )
            != readiness_bytes
        ):
            raise AttemptLedgerError(
                "runtime request readiness binding is invalid"
            )


def _validate_passed_translation_evidence(
    output_directory: object,
) -> None:
    from tools.guide_gates.run_final_real_translation import (
        validate_completed_final_translation_evidence,
    )

    try:
        validate_completed_final_translation_evidence(
            Path(str(output_directory))
        )
    except (OSError, ValueError) as exc:
        raise AttemptLedgerError(
            "translation terminal evidence is invalid"
        ) from exc


def _validate_passed_release_browser_evidence(
    output_directory: object,
) -> None:
    from tools.guide_gates.run_mainline_contract_browser_audit import (
        AuditBundleError,
        validate_completed_release_browser_evidence,
    )

    try:
        validate_completed_release_browser_evidence(
            Path(str(output_directory))
        )
    except (AuditBundleError, OSError, ValueError) as exc:
        raise AttemptLedgerError(
            "release browser terminal evidence is invalid"
        ) from exc


def _terminal_evidence_manifest(
    *,
    output_directory: object,
    evidence_directory: object,
) -> dict[str, object]:
    output_root = Path(str(output_directory)).resolve()
    evidence_root = Path(str(evidence_directory)).resolve()
    if (
        not output_root.is_dir()
        or output_root.is_symlink()
        or not evidence_root.is_dir()
        or evidence_root.is_symlink()
        or (
            evidence_root != output_root
            and output_root not in evidence_root.parents
        )
    ):
        raise AttemptLedgerError("failure evidence is invalid")
    files: dict[str, str] = {}
    for candidate in sorted(evidence_root.rglob("*")):
        if candidate.is_symlink():
            raise AttemptLedgerError("failure evidence is invalid")
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(output_root).as_posix()
        files[relative] = sha256(
            _read_regular_file_once(
                candidate,
                label="terminal evidence",
            )
        ).hexdigest()
    if not files:
        raise AttemptLedgerError("failure evidence is invalid")
    return {
        "schema_version": "guide-attempt-terminal-evidence-v1",
        "root": str(evidence_root),
        "sha256_by_path": files,
    }


def _require_terminal_evidence_manifest(
    manifest: Mapping[str, object],
    *,
    output_directory: object,
) -> None:
    output_root = Path(str(output_directory)).resolve()
    evidence_root = Path(str(manifest.get("root"))).resolve()
    hashes = manifest.get("sha256_by_path")
    if (
        manifest.get("schema_version")
        != "guide-attempt-terminal-evidence-v1"
        or not isinstance(hashes, dict)
        or not hashes
        or (
            evidence_root != output_root
            and output_root not in evidence_root.parents
        )
    ):
        raise AttemptLedgerError("terminal evidence changed")
    current = _terminal_evidence_manifest(
        output_directory=output_root,
        evidence_directory=evidence_root,
    )
    if current != dict(manifest):
        raise AttemptLedgerError("terminal evidence changed")


def _require_recorded_terminal_evidence_manifest(
    manifest: Mapping[str, object],
    *,
    output_directory: object,
    allowed_additional_subdirectories: tuple[str, ...] = (),
) -> None:
    raw_output_root = Path(str(output_directory))
    raw_evidence_root = Path(str(manifest.get("root")))
    output_root = raw_output_root.resolve()
    evidence_root = raw_evidence_root.resolve()
    hashes = manifest.get("sha256_by_path")
    if (
        manifest.get("schema_version")
        != "guide-attempt-terminal-evidence-v1"
        or raw_output_root.is_symlink()
        or not output_root.is_dir()
        or raw_evidence_root.is_symlink()
        or not evidence_root.is_dir()
        or (
            evidence_root != output_root
            and output_root not in evidence_root.parents
        )
        or not isinstance(hashes, dict)
        or not hashes
    ):
        raise AttemptLedgerError("terminal evidence changed")
    for relative_text, expected_sha256 in hashes.items():
        if (
            not isinstance(relative_text, str)
            or not relative_text
            or not _is_sha256(expected_sha256)
        ):
            raise AttemptLedgerError("terminal evidence changed")
        relative = Path(relative_text)
        if (
            relative.is_absolute()
            or relative.as_posix() != relative_text
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise AttemptLedgerError("terminal evidence changed")
        candidate = output_root / relative
        try:
            resolved_candidate = candidate.resolve(strict=True)
        except OSError as exc:
            raise AttemptLedgerError(
                "terminal evidence changed"
            ) from exc
        if (
            resolved_candidate != evidence_root
            and evidence_root not in resolved_candidate.parents
        ):
            raise AttemptLedgerError("terminal evidence changed")
        try:
            current_sha256 = sha256(
                _read_regular_file_once(
                    candidate,
                    label="terminal evidence",
                )
            ).hexdigest()
        except AttemptLedgerError as exc:
            raise AttemptLedgerError(
                "terminal evidence changed"
            ) from exc
        if current_sha256 != expected_sha256:
            raise AttemptLedgerError("terminal evidence changed")
    recorded_paths = set(hashes)
    for candidate in sorted(evidence_root.rglob("*")):
        if candidate.is_symlink():
            raise AttemptLedgerError("terminal evidence changed")
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(output_root).as_posix()
        if relative in recorded_paths:
            continue
        relative_parts = Path(relative).parts
        if any(
            relative_parts
            and relative_parts[0] == allowed
            for allowed in allowed_additional_subdirectories
        ):
            continue
        raise AttemptLedgerError("terminal evidence changed")


def complete_attempt(
    path: str | Path,
    *,
    result: Literal["passed", "failed"],
    first_failure_turn_id: str | None = None,
    first_failure_owner: str | None = None,
    failure_code: str | None = None,
    evidence_directory: str | None = None,
    local_reproduction: str | None = None,
    focused_test: str | None = None,
    shared_owner_repair: str | None = None,
    independent_audit: str | None = None,
) -> dict[str, Any]:
    context_path = Path(path)
    context, context_sha256 = _read_attempt_context_once(context_path)
    ledger = Path(str(context.get("ledger_path")))
    readiness_file = Path(str(context.get("readiness_path")))
    _verify_current_readiness(
        readiness_path=readiness_file,
        ledger_path=ledger,
        expected_manifest_sha256=str(
            context.get("expected_manifest_sha256")
        ),
    )
    readiness_binding = _capture_readiness_binding(readiness_file)
    phase_attempt_ids = context.get("phase_attempt_ids")
    if not isinstance(phase_attempt_ids, dict):
        raise AttemptLedgerError("attempt context is invalid")
    phase = attempt_context_phase(context)
    lifecycle = (
        _runtime_request_lifecycle_lock(
            context_path,
            shared=False,
        )
        if phase in {"bounded", "browser"}
        else nullcontext()
    )
    with lifecycle, _ledger_lock(ledger) as binding:
        _recover_orphan_temp(ledger, binding=binding)
        locked_context, locked_context_sha256 = (
            _read_attempt_context_once(context_path)
        )
        if (
            locked_context != context
            or locked_context_sha256 != context_sha256
        ):
            raise AttemptLedgerError(
                "attempt context content mismatch"
            )
        payload = _read_ledger_unlocked(ledger, binding=binding)
        _require_current_readiness_binding(
            readiness_path=readiness_file,
            binding=readiness_binding,
        )
        matching_phases = [
            phase
            for phase, attempt_id in phase_attempt_ids.items()
            if any(
                isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
                and item.get("context_path")
                == str(context_path.resolve())
                for item in payload["attempts"]
            )
        ]
        if len(matching_phases) != 1:
            raise AttemptLedgerError(
                "attempt context phase is ambiguous"
            )
        phase = matching_phases[0]
        attempt = _attempt_for_context(
            payload,
            context_path=context_path,
            phase=phase,
        )
        _validate_context_allocation(
            payload=payload,
            context=context,
            context_path=context_path,
            context_sha256=context_sha256,
            attempt=attempt,
        )
        authorization = _authorization(
            payload,
            attempt["retry_authorization_id"],
        )
        if (
            authorization.get("state") != "consumed"
            or attempt.get("result") != "consumed"
            or authorization.get("readiness_sha256")
            != readiness_binding[0]
            or context.get("readiness_sha256")
            != readiness_binding[0]
        ):
            raise AttemptLedgerError(
                "attempt must be consumed before completion"
            )
        if result == "passed":
            if phase == "bounded":
                _validate_passed_bounded_browser_evidence(
                    context["output_directory"]
                )
            elif phase == "translation":
                _validate_passed_translation_evidence(
                    context["output_directory"]
                )
            else:
                _validate_passed_release_browser_evidence(
                    context["output_directory"]
                )
        if phase in {"bounded", "browser"}:
            validate_runtime_bound_attempt_attestation(
                context_path=context_path,
                context=context,
                context_sha256=context_sha256,
                attempt=attempt,
                ledger=payload,
                require_browser_summary=(result == "passed"),
            )
            registrations = attempt.get("runtime_registrations")
            registration_id = attempt["runtime_attestation"].get(
                "runtime_registration_id"
            )
            matches = (
                [
                    item
                    for item in registrations
                    if (
                        isinstance(item, dict)
                        and item.get("registration_id")
                        == registration_id
                        and item.get("state") == "consumed"
                    )
                ]
                if isinstance(registrations, list)
                else []
            )
            if len(matches) != 1:
                raise AttemptLedgerError(
                    "runtime registration is not completable"
                )
            matches[0]["state"] = "terminated"
            matches[0]["terminated_at"] = _utc_now()
        completed_local_reproduction = (
            local_reproduction or attempt["local_reproduction"]
        )
        completed_focused_test = focused_test or attempt["focused_test"]
        completed_shared_owner_repair = (
            shared_owner_repair or attempt["shared_owner_repair"]
        )
        completed_independent_audit = (
            independent_audit or attempt["independent_audit"]
        )
        if result == "failed" and not all(
            isinstance(value, str) and value
            for value in (
                first_failure_turn_id,
                first_failure_owner,
                failure_code,
                evidence_directory,
            )
        ):
            raise AttemptLedgerError(
                "failed attempt requires complete failure evidence"
            )
        terminal_evidence = _terminal_evidence_manifest(
            output_directory=context["output_directory"],
            evidence_directory=(
                context["output_directory"]
                if result == "passed"
                else evidence_directory
            ),
        )
        authorization["state"] = result
        authorization["completed_at"] = _utc_now()
        attempt.update(
            {
                "result": result,
                "first_failure_turn_id": first_failure_turn_id,
                "first_failure_owner": first_failure_owner,
                "failure_code": failure_code,
                "evidence_directory": (
                    evidence_directory
                    or attempt["evidence_directory"]
                ),
                "local_reproduction": completed_local_reproduction,
                "focused_test": completed_focused_test,
                "shared_owner_repair": completed_shared_owner_repair,
                "independent_audit": completed_independent_audit,
                "terminal_evidence": terminal_evidence,
                "completed_at": _utc_now(),
            }
        )
        payload["revision"] += 1
        payload["circuit_state"] = _circuit_state(payload)
        _append_revision(
            payload,
            operation="attempt_completed",
            attempt_id=str(attempt["attempt_id"]),
            authorization_id=str(
                authorization["authorization_id"]
            ),
        )
        final_context, final_context_sha256 = (
            _read_attempt_context_once(context_path)
        )
        if (
            final_context != context
            or final_context_sha256 != context_sha256
        ):
            raise AttemptLedgerError(
                "attempt context content mismatch"
            )
        _require_current_readiness_binding(
            readiness_path=readiness_file,
            binding=readiness_binding,
        )
        _require_terminal_evidence_manifest(
            terminal_evidence,
            output_directory=context["output_directory"],
        )
        _atomic_write_ledger(ledger, payload, binding=binding)
        return deepcopy(attempt)


def reclassify_failed_attempt(
    *,
    ledger_path: str | Path,
    attempt_id: str,
    independent_audit_path: str | Path,
) -> dict[str, Any]:
    if not isinstance(attempt_id, str) or not attempt_id:
        raise AttemptLedgerError("attempt ID is invalid")
    ledger = Path(ledger_path)
    audit_path = Path(independent_audit_path)
    preflight_payload = read_ledger(ledger)
    preflight_matches = [
        attempt
        for attempt in preflight_payload["attempts"]
        if isinstance(attempt, dict)
        and attempt.get("attempt_id") == attempt_id
    ]
    if len(preflight_matches) != 1:
        raise AttemptLedgerError("attempt is unknown")
    preflight_audit = _load_json_object(
        audit_path,
        label="failure reclassification audit",
    )
    preflight_repair_files = preflight_audit.get(
        "repair_evidence_files"
    )
    preflight_failure_code = preflight_audit.get("failure_code")
    if (
        not isinstance(preflight_failure_code, str)
        or not isinstance(preflight_repair_files, dict)
    ):
        raise AttemptLedgerError(
            "failure reclassification audit is invalid"
        )
    _validate_reclassification_repair(
        failure_code=preflight_failure_code,
        repair_files=preflight_repair_files,
        error_message=(
            "failure reclassification repair evidence is invalid"
        ),
    )
    preflight_revision = preflight_payload["revision"]
    preflight_revision_hash = preflight_payload[
        "revision_chain"
    ][-1]["revision_hash"]
    preflight_audit_sha256 = _file_sha256(audit_path)
    preflight_repair_hashes = {
        name: _file_sha256(Path(str(path)))
        for name, path in preflight_repair_files.items()
        if (
            name in _RECLASSIFICATION_REPAIR_EVIDENCE_KEYS
            and Path(str(path)).is_file()
        )
    }
    with _ledger_lock(ledger) as binding:
        _recover_orphan_temp(ledger, binding=binding)
        payload = _read_ledger_unlocked(ledger, binding=binding)
        if (
            payload["revision"] != preflight_revision
            or payload["revision_chain"][-1]["revision_hash"]
            != preflight_revision_hash
            or _file_sha256(audit_path) != preflight_audit_sha256
        ):
            raise AttemptLedgerError(
                "reclassification evidence changed during validation"
            )
        matches = [
            attempt
            for attempt in payload["attempts"]
            if isinstance(attempt, dict)
            and attempt.get("attempt_id") == attempt_id
        ]
        if len(matches) != 1:
            raise AttemptLedgerError("attempt is unknown")
        attempt = matches[0]
        if attempt.get("result") != "failed":
            raise AttemptLedgerError(
                "only a failed attempt can be reclassified"
            )
        audit = _load_json_object(
            audit_path,
            label="failure reclassification audit",
        )
        evidence_directory = Path(
            str(attempt.get("evidence_directory"))
        ).resolve()
        context_path = Path(str(attempt.get("context_path")))
        if (
            not context_path.is_file()
            or attempt.get("context_sha256")
            != _file_sha256(context_path)
        ):
            raise AttemptLedgerError(
                "failure reclassification context mismatch"
            )
        context = _load_json_object(
            context_path,
            label="attempt context",
        )
        readiness_path = Path(str(context.get("readiness_path")))
        if (
            not readiness_path.is_file()
            or context.get("readiness_sha256")
            != _file_sha256(readiness_path)
        ):
            raise AttemptLedgerError(
                "failure reclassification readiness mismatch"
            )
        readiness = _load_json_object(
            readiness_path,
            label="readiness",
        )
        attempt_record_sha256 = _attempt_allocation_sha256(attempt)
        evidence_hashes = audit.get("reviewed_evidence_sha256")
        repair_files = audit.get("repair_evidence_files")
        repair_hashes = audit.get("repair_evidence_sha256")
        current_repair_hashes = (
            {
                name: _file_sha256(Path(str(path)))
                for name, path in repair_files.items()
                if (
                    name in _RECLASSIFICATION_REPAIR_EVIDENCE_KEYS
                    and Path(str(path)).is_file()
                )
            }
            if isinstance(repair_files, dict)
            else {}
        )
        new_owner = audit.get("first_failure_owner")
        new_code = audit.get("failure_code")
        expected_new_owner = (
            _RECLASSIFICATION_OWNER_BY_CODE.get(new_code)
            if (
                isinstance(new_code, str)
                and new_code in _ACTIVE_RECLASSIFICATION_CODES
            )
            else None
        )
        if expected_new_owner is None:
            raise AttemptLedgerError(
                "unsupported failure reclassification"
            )
        if new_code in _INDEXED_RUNTIME_FAILURE_CODES:
            (
                current_evidence_hashes,
                evidence_bundle_sha256,
            ) = _recorded_failure_evidence_binding(
                attempt,
                evidence_directory=evidence_directory,
            )
        else:
            current_evidence_hashes = {
                name: _file_sha256(evidence_directory / name)
                for name in _FAILURE_EVIDENCE_FILES
                if (evidence_directory / name).is_file()
            }
            if set(current_evidence_hashes) != _FAILURE_EVIDENCE_FILES:
                raise AttemptLedgerError(
                    "failure reclassification evidence mismatch"
                )
            evidence_bundle_sha256 = _failure_evidence_sha256(
                evidence_directory
            )
        if (
            audit.get("schema_version")
            != "guide-smoke-failure-reclassification-v1"
            or audit.get("passed") is not True
            or audit.get("plan_revision")
            != attempt.get("plan_revision")
            or audit.get("attempt_id") != attempt_id
            or audit.get("first_failure_turn_id")
            != attempt.get("first_failure_turn_id")
            or audit.get("code_revision")
            != attempt.get("code_revision")
            or audit.get("attempt_context_sha256")
            != attempt.get("context_sha256")
            or audit.get("attempt_record_sha256")
            != context.get("attempt_record_sha256")
            or audit.get("attempt_record_sha256")
            != attempt_record_sha256
            or audit.get("readiness_path")
            != str(readiness_path.resolve())
            or audit.get("readiness_sha256")
            != context.get("readiness_sha256")
            or audit.get("protected_payload_sha256")
            != readiness.get("protected_payload_sha256")
            or audit.get("pre_reclassification_ledger_revision")
            != payload["revision"]
            or Path(
                str(audit.get("evidence_directory"))
            ).resolve()
            != evidence_directory
            or audit.get("previous_failure_owner")
            != attempt.get("first_failure_owner")
            or audit.get("previous_failure_code")
            != attempt.get("failure_code")
            or not isinstance(new_owner, str)
            or not new_owner
            or new_owner != expected_new_owner
            or new_owner == attempt.get("first_failure_owner")
            or not isinstance(new_code, str)
            or not new_code
            or not isinstance(audit.get("conclusion"), str)
            or not audit["conclusion"]
            or not isinstance(evidence_hashes, dict)
            or evidence_hashes != current_evidence_hashes
            or audit.get("evidence_bundle_sha256")
            != evidence_bundle_sha256
            or not isinstance(repair_files, dict)
            or set(repair_files)
            != _RECLASSIFICATION_REPAIR_EVIDENCE_KEYS
            or not isinstance(repair_hashes, dict)
            or set(repair_hashes)
            != _RECLASSIFICATION_REPAIR_EVIDENCE_KEYS
            or current_repair_hashes != repair_hashes
            or current_repair_hashes != preflight_repair_hashes
        ):
            raise AttemptLedgerError(
                "failure reclassification audit is invalid"
            )
        if (
            new_code not in _INDEXED_RUNTIME_FAILURE_CODES
            and any(
                not (evidence_directory / name).is_file()
                or evidence_hashes.get(name)
                != _file_sha256(evidence_directory / name)
                for name in _FAILURE_EVIDENCE_FILES
            )
        ):
            raise AttemptLedgerError(
                "failure reclassification evidence mismatch"
            )
        history = attempt.get("failure_reclassifications", [])
        if not isinstance(history, list):
            raise AttemptLedgerError(
                "failure reclassification history is invalid"
            )
        history.append(
            {
                "previous_failure_owner": (
                    attempt["first_failure_owner"]
                ),
                "previous_failure_code": attempt["failure_code"],
                "first_failure_owner": new_owner,
                "failure_code": new_code,
                "first_failure_turn_id": attempt[
                    "first_failure_turn_id"
                ],
                "code_revision": attempt["code_revision"],
                "evidence_bundle_sha256": evidence_bundle_sha256,
                "reviewed_evidence_sha256": deepcopy(
                    evidence_hashes
                ),
                "attempt_context_sha256": attempt[
                    "context_sha256"
                ],
                "attempt_record_sha256": attempt_record_sha256,
                "readiness_path": str(readiness_path.resolve()),
                "readiness_sha256": context["readiness_sha256"],
                "protected_payload_sha256": readiness[
                    "protected_payload_sha256"
                ],
                "repair_evidence_files": deepcopy(repair_files),
                "repair_evidence_sha256": deepcopy(repair_hashes),
                "pre_reclassification_ledger_revision": (
                    payload["revision"]
                ),
                "independent_audit_path": str(
                    audit_path.resolve()
                ),
                "independent_audit_sha256": _file_sha256(
                    audit_path
                ),
            }
        )
        attempt["first_failure_owner"] = new_owner
        attempt["failure_code"] = new_code
        attempt["failure_reclassifications"] = history
        payload["revision"] += 1
        payload["circuit_state"] = _circuit_state(payload)
        _append_revision(
            payload,
            operation="failure_reclassified",
            attempt_id=str(attempt["attempt_id"]),
            authorization_id=str(
                attempt["retry_authorization_id"]
            ),
        )
        _atomic_write_ledger(ledger, payload, binding=binding)
        return deepcopy(attempt)


def _context_for_result(
    *,
    phase: Phase,
    result: str | None,
    readiness_path: str | Path,
    ledger_path: str | Path,
    latest: bool,
) -> Path:
    readiness = _readiness(Path(readiness_path))
    payload = read_ledger(ledger_path)
    phase_matches = [
        attempt
        for attempt in payload["attempts"]
        if isinstance(attempt, dict)
        and attempt.get("trajectory_set") == phase
        and attempt.get("plan_revision") == readiness["plan_revision"]
    ]
    if latest:
        if not phase_matches:
            raise AttemptLedgerError(
                "matching attempt context is missing"
            )
        selected = phase_matches[-1]
        if selected.get("result") != result:
            raise AttemptLedgerError(
                "latest attempt result mismatch"
            )
        matches = [selected]
    else:
        matches = [
            attempt
            for attempt in phase_matches
            if attempt.get("result") not in _TERMINAL_RESULTS
        ]
    if not matches:
        raise AttemptLedgerError("matching attempt context is missing")
    if not latest and len(matches) != 1:
        raise AttemptLedgerError(
            "current attempt context is ambiguous"
        )
    selected = matches[-1]
    context_path = Path(str(selected.get("context_path")))
    read_attempt_context(
        context_path,
        ledger_path=ledger_path,
        readiness_path=readiness_path,
    )
    return context_path


def current_attempt_context(
    *,
    phase: Phase,
    readiness_path: str | Path,
    ledger_path: str | Path,
) -> Path:
    return _context_for_result(
        phase=phase,
        result=None,
        readiness_path=readiness_path,
        ledger_path=ledger_path,
        latest=False,
    )


def latest_attempt_context(
    *,
    phase: Phase,
    result: Literal["passed", "failed"],
    readiness_path: str | Path,
    ledger_path: str | Path,
) -> Path:
    return _context_for_result(
        phase=phase,
        result=result,
        readiness_path=readiness_path,
        ledger_path=ledger_path,
        latest=True,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser("init")
    initialize.add_argument("--ledger", type=Path, required=True)
    initialize.add_argument(
        "--historical-attempts",
        type=Path,
        required=True,
    )

    migrate = subparsers.add_parser("migrate-v1")
    migrate.add_argument("--source", type=Path, required=True)
    migrate.add_argument("--ledger", type=Path, required=True)
    migrate.add_argument("--source-sha256", required=True)

    checkpoint = subparsers.add_parser("checkpoint-v2")
    checkpoint.add_argument("--ledger", type=Path, required=True)
    checkpoint.add_argument("--manifest", type=Path, required=True)
    checkpoint.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )

    authorize = subparsers.add_parser("authorize")
    authorize.add_argument(
        "--phase",
        choices=("bounded", "translation", "browser"),
        required=True,
    )
    authorize.add_argument("--readiness", type=Path, required=True)
    authorize.add_argument("--ledger", type=Path, required=True)
    authorize.add_argument(
        "--independent-audit",
        type=Path,
        required=True,
    )
    authorize.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )

    for name in ("allocate", "allocate-child"):
        allocate = subparsers.add_parser(name)
        allocate.add_argument(
            "--phase",
            choices=("bounded", "translation", "browser"),
            required=True,
        )
        allocate.add_argument(
            "--authorization-id",
            required=True,
        )
        allocate.add_argument("--ledger", type=Path, required=True)
        allocate.add_argument("--readiness", type=Path, required=True)
        allocate.add_argument(
            "--output-root",
            type=Path,
            required=True,
        )
        if name == "allocate-child":
            allocate.add_argument(
                "--parent-context",
                type=Path,
                required=True,
            )
            allocate.add_argument(
                "--require-summary-phase",
                choices=("backend",),
                required=True,
            )
            allocate.add_argument(
                "--require-summary-result",
                choices=("passed", "failed"),
                required=True,
            )

    consume = subparsers.add_parser("consume")
    consume.add_argument(
        "--phase",
        choices=("bounded", "translation", "browser"),
        required=True,
    )
    consume.add_argument("--attempt-context", type=Path, required=True)
    consume.add_argument("--ledger", type=Path, required=True)
    consume.add_argument("--readiness", type=Path, required=True)

    complete = subparsers.add_parser("complete")
    complete.add_argument("--attempt-context", type=Path, required=True)
    complete.add_argument(
        "--result",
        choices=("passed", "failed"),
        required=True,
    )

    reclassify = subparsers.add_parser("reclassify")
    reclassify.add_argument("--ledger", type=Path, required=True)
    reclassify.add_argument("--attempt-id", required=True)
    reclassify.add_argument(
        "--independent-audit",
        type=Path,
        required=True,
    )

    for name in ("current", "latest"):
        lookup = subparsers.add_parser(name)
        lookup.add_argument(
            "--phase",
            choices=("bounded", "translation", "browser"),
            required=True,
        )
        lookup.add_argument("--readiness", type=Path, required=True)
        lookup.add_argument("--ledger", type=Path, required=True)
        if name == "latest":
            lookup.add_argument(
                "--result",
                choices=("passed", "failed"),
                required=True,
            )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "init":
        try:
            historical = json.loads(
                args.historical_attempts.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise AttemptLedgerError(
                "historical attempts are invalid"
            ) from exc
        if not isinstance(historical, list):
            raise AttemptLedgerError(
                "historical attempts are invalid"
            )
        initialize_ledger(args.ledger, attempts=historical)
        return 0
    if args.command == "migrate-v1":
        migrate_legacy_ledger(
            source_path=args.source,
            target_path=args.ledger,
            expected_source_sha256=args.source_sha256,
        )
        return 0
    if args.command == "checkpoint-v2":
        checkpoint_ledger(
            ledger_path=args.ledger,
            manifest_path=args.manifest,
            expected_manifest_sha256=args.expected_manifest_sha256,
        )
        return 0
    if args.command == "authorize":
        print(
            authorize_attempt(
                phase=args.phase,
                readiness_path=args.readiness,
                ledger_path=args.ledger,
                independent_audit_path=args.independent_audit,
                expected_manifest_sha256=(
                    args.expected_manifest_sha256
                ),
            )
        )
        return 0
    if args.command in {"allocate", "allocate-child"}:
        print(
            allocate_attempt(
                phase=args.phase,
                authorization_id=args.authorization_id,
                ledger_path=args.ledger,
                readiness_path=args.readiness,
                output_root=args.output_root,
                parent_context=(
                    args.parent_context
                    if args.command == "allocate-child"
                    else None
                ),
                require_summary_phase=(
                    args.require_summary_phase
                    if args.command == "allocate-child"
                    else None
                ),
                require_summary_result=(
                    args.require_summary_result
                    if args.command == "allocate-child"
                    else None
                ),
            )
        )
        return 0
    if args.command == "consume":
        consume_attempt_context(
            args.attempt_context,
            phase=args.phase,
            ledger_path=args.ledger,
            readiness_path=args.readiness,
        )
        print(args.attempt_context)
        return 0
    if args.command == "complete":
        complete_attempt(
            args.attempt_context,
            result=args.result,
        )
        print(args.attempt_context)
        return 0
    if args.command == "reclassify":
        reclassified = reclassify_failed_attempt(
            ledger_path=args.ledger,
            attempt_id=args.attempt_id,
            independent_audit_path=args.independent_audit,
        )
        print(reclassified["attempt_id"])
        return 0
    if args.command == "current":
        print(
            current_attempt_context(
                phase=args.phase,
                readiness_path=args.readiness,
                ledger_path=args.ledger,
            )
        )
        return 0
    print(
        latest_attempt_context(
            phase=args.phase,
            result=args.result,
            readiness_path=args.readiness,
            ledger_path=args.ledger,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
