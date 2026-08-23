from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4


Phase = Literal["bounded", "translation", "browser"]
AttemptResult = Literal["allocated", "consumed", "passed", "failed"]
_SCHEMA_VERSION = "guide-smoke-attempt-ledger-v1"
_CONTEXT_SCHEMA_VERSION = "guide-smoke-attempt-context-v1"
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


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


@contextmanager
def _ledger_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _lock_path(path)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _validate_ledger(payload: object) -> dict[str, Any]:
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
    return payload


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AttemptLedgerError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise AttemptLedgerError(f"{label} is invalid")
    return payload


def _recover_orphan_temp(path: Path) -> None:
    temporary = ledger_temp_path(path)
    if not temporary.exists():
        return
    if not path.is_file():
        raise AttemptLedgerError("canonical ledger is invalid")
    _validate_ledger(
        _load_json_object(path, label="canonical ledger")
    )
    temporary.unlink()


def _read_ledger_unlocked(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AttemptLedgerError("canonical ledger is missing")
    payload = _validate_ledger(
        _load_json_object(path, label="canonical ledger")
    )
    _verify_failure_reclassifications(payload)
    return payload


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
            raise AttemptLedgerError(
                "failure reclassification evidence mismatch"
            )
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


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_ledger(path: Path, payload: dict[str, Any]) -> None:
    temporary = ledger_temp_path(path)
    data = _canonical_bytes(payload)
    with temporary.open("wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


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
        owner = attempt.get("first_failure_owner")
        if isinstance(owner, str) and owner:
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
    ledger = Path(path)
    with _ledger_lock(ledger):
        _recover_orphan_temp(ledger)
        if ledger.exists():
            raise AttemptLedgerError("canonical ledger already exists")
        payload: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "revision": 0,
            "circuit_state": "closed",
            "attempts": [deepcopy(item) for item in attempts],
            "authorizations": [],
        }
        payload["circuit_state"] = _circuit_state(payload)
        _validate_ledger(payload)
        _atomic_write_ledger(ledger, payload)
        return deepcopy(payload)


def read_ledger(path: str | Path) -> dict[str, Any]:
    ledger = Path(path)
    with _ledger_lock(ledger):
        _recover_orphan_temp(ledger)
        return deepcopy(_read_ledger_unlocked(ledger))


def compare_and_swap_ledger(
    path: str | Path,
    *,
    expected_revision: int,
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    ledger = Path(path)
    with _ledger_lock(ledger):
        _recover_orphan_temp(ledger)
        current = _read_ledger_unlocked(ledger)
        if current["revision"] != expected_revision:
            raise AttemptLedgerError("stale ledger revision")
        replacement = mutate(deepcopy(current))
        if not isinstance(replacement, dict):
            raise AttemptLedgerError(
                "ledger mutation must return an object"
            )
        replacement["revision"] = expected_revision + 1
        replacement["circuit_state"] = _circuit_state(replacement)
        _validate_ledger(replacement)
        _atomic_write_ledger(ledger, replacement)
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
        or payload.get("circuit_state") != "closed"
        or payload.get("invalid_clarification_count") != 0
        or any(payload.get(field) is not True for field in required_true)
    ):
        raise AttemptLedgerError("readiness is not eligible")
    return payload


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


def authorize_attempt(
    *,
    phase: Phase,
    readiness_path: str | Path,
    ledger_path: str | Path,
    independent_audit_path: str | Path,
    readiness_verifier: Callable[..., dict[str, Any]] | None = None,
) -> str:
    readiness_file = Path(readiness_path)
    audit_file = Path(independent_audit_path)
    if readiness_verifier is None:
        from tools.guide_gates.build_task11_readiness import (
            verify_task11_readiness,
        )

        readiness_verifier = verify_task11_readiness
    readiness_verifier(
        readiness_path=readiness_file,
        ledger_path=ledger_path,
    )
    readiness = _readiness(readiness_file)
    audit = _independent_audit(path=audit_file, readiness=readiness)
    ledger = Path(ledger_path)
    with _ledger_lock(ledger):
        _recover_orphan_temp(ledger)
        payload = _read_ledger_unlocked(ledger)
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
        previous = _latest_failure(
            payload,
            plan_revision=plan_revision,
        )
        if previous is None:
            owner = "planned_gate"
            repair_epoch = 0
        else:
            owner = previous.get("first_failure_owner")
            if not isinstance(owner, str) or not owner:
                raise AttemptLedgerError(
                    "historical failure owner is invalid"
                )
            repair_epoch = failures[owner]
        if (
            audit.get("first_failure_owner") != owner
            or audit.get("repair_epoch") != repair_epoch
        ):
            raise AttemptLedgerError(
                "independent audit repair epoch mismatch"
            )
        repair_evidence = {
            key: audit.get(key)
            for key in (
                "local_reproduction",
                "focused_test",
                "shared_owner_repair",
            )
        }
        if owner != "planned_gate" and not all(
            isinstance(value, str) and value
            for value in repair_evidence.values()
        ):
            raise AttemptLedgerError(
                "independent audit repair evidence is incomplete"
            )
        if any(
            authorization.get("phase") == phase
            and authorization.get("plan_revision") == plan_revision
            and authorization.get("state") in {"allocated", "consumed"}
            for authorization in payload["authorizations"]
            if isinstance(authorization, dict)
        ):
            raise AttemptLedgerError(
                "phase already has an active authorization"
            )
        authorization_id = f"auth_{uuid4().hex}"
        payload["authorizations"].append(
            {
                "authorization_id": authorization_id,
                "phase": phase,
                "plan_revision": plan_revision,
                "repair_epoch": repair_epoch,
                "first_failure_owner": owner,
                "readiness_path": str(readiness_file.resolve()),
                "readiness_sha256": _file_sha256(readiness_file),
                "independent_audit_path": str(audit_file.resolve()),
                "independent_audit_sha256": _file_sha256(audit_file),
                "repair_evidence": repair_evidence,
                "state": "allocated",
                "attempt_id": None,
                "created_at": _utc_now(),
            }
        )
        payload["revision"] += 1
        payload["circuit_state"] = _circuit_state(payload)
        _atomic_write_ledger(ledger, payload)
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
    with _ledger_lock(ledger):
        _recover_orphan_temp(ledger)
        payload = _read_ledger_unlocked(ledger)
        authorization = _authorization(payload, authorization_id)
        if authorization.get("state") != "allocated":
            raise AttemptLedgerError("authorization is not allocatable")
        if authorization.get("attempt_id") is not None:
            raise AttemptLedgerError(
                "authorization already has an attempt"
            )
        if (
            authorization.get("phase") != phase
            or authorization.get("plan_revision")
            != readiness.get("plan_revision")
            or authorization.get("readiness_path")
            != str(readiness_file.resolve())
            or authorization.get("readiness_sha256")
            != _file_sha256(readiness_file)
        ):
            raise AttemptLedgerError(
                "authorization does not match allocation"
            )
        attempt_id = _next_attempt_id(payload, phase=phase)
        output_directory = Path(output_root).resolve() / attempt_id
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
        }
        context = {
            "schema_version": _CONTEXT_SCHEMA_VERSION,
            "context_id": f"context_{uuid4().hex}",
            "parent_attempt_id": None,
            "phase_attempt_ids": {phase: attempt_id},
            "phase_authorization_ids": {
                phase: authorization_id,
            },
            "output_directory": str(output_directory),
            "readiness_path": str(readiness_file.resolve()),
            "readiness_sha256": _file_sha256(readiness_file),
            "ledger_path": str(ledger.resolve()),
            "allocated_ledger_revision": next_revision,
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
            ):
                raise AttemptLedgerError(
                    "parent attempt context is invalid"
                )
            context["parent_attempt_id"] = next(
                reversed(parent_ids.values())
            )
            context["phase_attempt_ids"] = {
                **parent_ids,
                phase: attempt_id,
            }
            context["phase_authorization_ids"] = {
                **parent_authorizations,
                phase: authorization_id,
            }
        attempt["context_sha256"] = sha256(
            _canonical_bytes(context)
        ).hexdigest()
        _write_immutable_json(context_path, context)
        authorization["attempt_id"] = attempt_id
        payload["attempts"].append(attempt)
        payload["revision"] = next_revision
        payload["circuit_state"] = _circuit_state(payload)
        _atomic_write_ledger(ledger, payload)
        return context_path


def read_attempt_context(
    path: str | Path,
    *,
    ledger_path: str | Path,
    readiness_path: str | Path,
) -> dict[str, Any]:
    context_path = Path(path)
    context = _load_json_object(
        context_path,
        label="attempt context",
    )
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
    current_attempt_id = next(reversed(attempt_ids.values()))
    current_attempt = next(
        attempt
        for attempt in payload["attempts"]
        if attempt.get("attempt_id") == current_attempt_id
    )
    if current_attempt.get("context_sha256") != _file_sha256(
        context_path
    ):
        raise AttemptLedgerError("attempt context content mismatch")
    if (
        current_attempt.get("context_path")
        != str(context_path.resolve())
        or context.get("attempt_record_sha256")
        != _attempt_allocation_sha256(current_attempt)
    ):
        raise AttemptLedgerError(
            "attempt context allocation is invalid"
        )
    allocated_revision = context.get("allocated_ledger_revision")
    if (
        not isinstance(allocated_revision, int)
        or allocated_revision > payload["revision"]
    ):
        raise AttemptLedgerError("attempt context ledger revision is invalid")
    return context


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


def consume_attempt_context(
    path: str | Path,
    *,
    phase: Phase,
    ledger_path: str | Path,
    readiness_path: str | Path,
) -> dict[str, Any]:
    context_path = Path(path)
    context = _load_json_object(
        context_path,
        label="attempt context",
    )
    readiness_file = Path(readiness_path)
    ledger = Path(ledger_path)
    with _ledger_lock(ledger):
        _recover_orphan_temp(ledger)
        payload = _read_ledger_unlocked(ledger)
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
        authorization = _authorization(
            payload,
            attempt["retry_authorization_id"],
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
            != _file_sha256(readiness_file)
        ):
            raise AttemptLedgerError("readiness changed after allocation")
        authorization["state"] = "consumed"
        authorization["consumed_at"] = _utc_now()
        attempt["result"] = "consumed"
        payload["revision"] += 1
        payload["circuit_state"] = _circuit_state(payload)
        _atomic_write_ledger(ledger, payload)
    return context


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
    context = _load_json_object(
        context_path,
        label="attempt context",
    )
    ledger = Path(str(context.get("ledger_path")))
    phase_attempt_ids = context.get("phase_attempt_ids")
    if not isinstance(phase_attempt_ids, dict):
        raise AttemptLedgerError("attempt context is invalid")
    matching_phases = [
        phase
        for phase, attempt_id in phase_attempt_ids.items()
        if any(
            isinstance(item, dict)
            and item.get("attempt_id") == attempt_id
            and item.get("context_path") == str(context_path.resolve())
            for item in read_ledger(ledger)["attempts"]
        )
    ]
    if len(matching_phases) != 1:
        raise AttemptLedgerError("attempt context phase is ambiguous")
    phase = matching_phases[0]
    with _ledger_lock(ledger):
        _recover_orphan_temp(ledger)
        payload = _read_ledger_unlocked(ledger)
        attempt = _attempt_for_context(
            payload,
            context_path=context_path,
            phase=phase,
        )
        authorization = _authorization(
            payload,
            attempt["retry_authorization_id"],
        )
        if (
            authorization.get("state") != "consumed"
            or attempt.get("result") != "consumed"
        ):
            raise AttemptLedgerError(
                "attempt must be consumed before completion"
            )
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
                "completed_at": _utc_now(),
            }
        )
        payload["revision"] += 1
        payload["circuit_state"] = _circuit_state(payload)
        _atomic_write_ledger(ledger, payload)
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
    with _ledger_lock(ledger):
        _recover_orphan_temp(ledger)
        payload = _read_ledger_unlocked(ledger)
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
        evidence_bundle_sha256 = _failure_evidence_sha256(
            evidence_directory
        )
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
            or new_owner == attempt.get("first_failure_owner")
            or not isinstance(new_code, str)
            or not new_code
            or not isinstance(audit.get("conclusion"), str)
            or not audit["conclusion"]
            or not isinstance(evidence_hashes, dict)
            or set(evidence_hashes) != _FAILURE_EVIDENCE_FILES
            or audit.get("evidence_bundle_sha256")
            != evidence_bundle_sha256
            or not isinstance(repair_files, dict)
            or set(repair_files)
            != _RECLASSIFICATION_REPAIR_EVIDENCE_KEYS
            or not isinstance(repair_hashes, dict)
            or set(repair_hashes)
            != _RECLASSIFICATION_REPAIR_EVIDENCE_KEYS
            or current_repair_hashes != repair_hashes
        ):
            raise AttemptLedgerError(
                "failure reclassification audit is invalid"
            )
        if any(
            not (evidence_directory / name).is_file()
            or evidence_hashes.get(name)
            != _file_sha256(evidence_directory / name)
            for name in _FAILURE_EVIDENCE_FILES
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
        _atomic_write_ledger(ledger, payload)
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
            allocate.add_argument("--require-summary-phase")
            allocate.add_argument("--require-summary-result")

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
    if args.command == "authorize":
        print(
            authorize_attempt(
                phase=args.phase,
                readiness_path=args.readiness,
                ledger_path=args.ledger,
                independent_audit_path=args.independent_audit,
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
