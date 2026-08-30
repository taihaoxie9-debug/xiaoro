from __future__ import annotations

import argparse
import ast
import base64
from collections.abc import Callable, Mapping
import ctypes
import errno
from hashlib import sha256
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Sequence
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from tools.guide_gates.attempt_ledger import (
    AttemptLedgerError,
    ledger_anchor,
    read_attempt_context,
    read_ledger,
    read_ledger_checkpoint_source,
    validate_runtime_bound_attempt_attestation,
    verify_ledger_checkpoint_authority,
    verify_ledger_extension,
)
from tools.guide_gates.runtime_auth import (
    RuntimeProofError,
    decode_runtime_private_key,
    encode_runtime_private_key,
    generate_runtime_keypair,
    runtime_public_key,
)
from tools.guide_gates.zero_api_network_guard import (
    ZERO_API_SANDBOX_PROFILE,
)


_MANIFEST_SCHEMA = "guide-task11-candidate-manifest-v1"
_FIXTURE_RUNTIME_PRIVATE_KEY_SCHEMA = (
    "guide-task11-fixture-runtime-private-key-v1"
)
_FIXTURE_RUNTIME_KEY_COUNT = 2
_RUNTIME_BROWSER_EVIDENCE_DIRECTORY = "runtime-browser-evidence"
_RUNTIME_BROWSER_ATTEMPTS = ("attempt-01", "attempt-02")
_RUNTIME_BROWSER_RELATIVE_BY_ROLE = {
    "runtime_network_report": "task11-zero-api-runtime-network.json",
    "desktop_summary": "fixture-browser-desktop/summary.json",
    "mobile_summary": "fixture-browser-mobile/summary.json",
}
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 0x00000004
_RUNTIME_IDENTITY_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-identity-v1\x00"
)
_RUNTIME_CHALLENGE_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-challenge-v1\x00"
)
_RUNTIME_REPORT_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-parent-report-v1\x00"
)
_RUNTIME_PRIVATE_KEY_DESTRUCTION_SCHEMA = (
    "guide-task11-runtime-private-key-destruction-v1"
)
_RUNTIME_PRIVATE_KEY_DESTRUCTION_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-runtime-private-key-destruction-v1\x00"
)
_READINESS_SCHEMA = "guide-task11-readiness-v1"
_RELEASE_READINESS_SCHEMA = "guide-task11-release-readiness-v1"
_PLAN_REVISION_PATTERN = re.compile(
    r"^Plan revision:\s*(\S+)\s*$",
    re.MULTILINE,
)
_TASK11_EPOCH_PATTERN = re.compile(
    r"^Task 11 evidence epoch:\s*repair-epoch-(\d+)\s*$",
    re.MULTILINE,
)
_FILE_LINE_PATTERN = re.compile(
    r"^- (Create|Modify|Test|Generate|Delete): `([^`]+)`$",
    re.MULTILINE,
)
_EXCLUDED_PATHS = (
    ".dbg/",
    ".tmp-*",
    "debug-*.md",
    "docs/audits/continuous-conversation/",
    "docs/audits/final-release/mainline-contract-closure/",
    "docs/superpowers/plans/2026-08-20-recording-ready-guide-path.md",
)
_RELEVANT_PREFIXES = (
    "app/",
    "data/canonical/",
    "tests/",
    "tools/",
    "docs/audits/semantic-turn-meaning/",
    "docs/superpowers/plans/",
)
_RELEVANT_ROOT_FILES = frozenset(
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
_FIXTURE_TURN_IDS = (
    "fixture-explore-recommendation",
    "fixture-fit-recommendation",
    "fixture-fit-clarification",
    "fixture-product-knowledge",
    "fixture-comparison",
    "fixture-image-identity",
    "fixture-image-fit-recommendation",
    "fixture-multi-image-comparison",
)
_SEMANTIC_CASES_PATH = (
    "tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl"
)
_PRODUCTION_MATRIX_CASES_PATH = (
    "tests/fixtures/guide/intent/"
    "task11_production_path_matrix_v1.jsonl"
)
_BOUNDED_BROWSER_TOOL_PATH = (
    "tools/guide_gates/run_mainline_contract_browser_audit.py"
)
_PRODUCTION_ACCEPTED_TURN_COUNT = 176
_PRODUCTION_MATRIX_TURN_COUNT = 177
_PRE_DECISION_REJECTION_COUNT = 1
_BOUNDED_TURN_COUNT = 9
_RUNTIME_LAYER_ORDER = [
    "translation",
    "compiler",
    "router",
    "processor",
    "reducer",
    "sqlite",
    "sse",
]
_INDEPENDENT_AUDIT_CHECKS = frozenset(
    {
        "manifest",
        "production_diff",
        "semantic_summary",
        "zero_api_summary",
        "single_path_architecture",
        "production_bridge_scan",
        "task12_execution_tools",
        "governance_source_contracts",
        "test_path_audit",
        "network_report",
        "runtime_network_report",
        "production_path_summary",
        "bounded_trajectory_messages",
        "desktop_summary",
        "mobile_summary",
    }
)


class _LocalStaticDependencyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paths: set[str] = set()

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
        relative = PurePosixPath(
            "app/static",
            parsed.path.removeprefix("/static/"),
        ).as_posix()
        self.paths.add(_normalized_path(relative))


def _required_local_static_dependencies(
    root: Path,
    protected_paths: Sequence[str],
) -> tuple[str, ...]:
    required: set[str] = set()
    for relative in protected_paths:
        if (
            not relative.startswith("app/static/")
            or not relative.endswith(".html")
        ):
            continue
        parser = _LocalStaticDependencyParser()
        parser.feed((root / relative).read_text(encoding="utf-8"))
        required.update(
            path for path in parser.paths if (root / path).is_file()
        )
    return tuple(sorted(required))


_HEX_40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_HEX_64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_IDENTITY_SCHEMA = "guide-zero-api-runtime-identity-v1"
_RUNTIME_CHALLENGE_SCHEMA = "guide-zero-api-runtime-challenge-v1"
_RUNTIME_IDENTITY_ARTIFACT = "runtime-identity.json"
_CONSUMED_CHALLENGE_ARTIFACT = (
    "consumed-runtime-health-challenge.json"
)
_MUTABLE_EVIDENCE_PATHS = (
    "docs/audits/final-release/mainline-contract-closure/"
    "smoke-attempt-ledger.json",
)
_EPOCH_EVIDENCE_RELATIVE_BY_ROLE = {
    "semantic_summary": "task11-semantic-matrix-summary.json",
    "zero_api_summary": "task11-zero-api-summary.json",
    "network_report": "task11-zero-api-network.json",
    "runtime_network_report": (
        f"{_RUNTIME_BROWSER_EVIDENCE_DIRECTORY}/"
        "task11-zero-api-runtime-network.json"
    ),
    "single_path_architecture": "task11-single-path-architecture.json",
    "test_path_audit": "task11-test-path-audit.json",
    "production_path_summary": "task11-production-path-summary.json",
    "independent_audit": "task11-independent-audit.json",
    "desktop_summary": (
        f"{_RUNTIME_BROWSER_EVIDENCE_DIRECTORY}/"
        "fixture-browser-desktop/summary.json"
    ),
    "mobile_summary": (
        f"{_RUNTIME_BROWSER_EVIDENCE_DIRECTORY}/"
        "fixture-browser-mobile/summary.json"
    ),
}
_FIXTURE_ROOT_ARTIFACTS = frozenset(
    {
        "browser-requests.json",
        "chromium-netlog.json",
        _CONSUMED_CHALLENGE_ARTIFACT,
        _RUNTIME_IDENTITY_ARTIFACT,
        "sandbox-audit.json",
        "sandbox-profile.sb",
        "seatbelt.raw.ndjson",
    }
)
_FIXTURE_TURN_ARTIFACTS = frozenset(
    {
        "console.json",
        "network.json",
        "presentation-contract.json",
        "request.json",
        "sandbox-audit.json",
        "screenshot.png",
        "stream.sse",
        "terminal-dom.json",
    }
)
_TASK12_RUNTIME_DATA_PATHS = (
    "data/canonical/core_products_v1_manifest.json",
    "data/canonical/core_products_v1.jsonl",
    "data/canonical/seed_product_images_v1_manifest.json",
    "data/canonical/seed_product_images_v1.jsonl",
)
_TASK12_EXECUTION_PATHS = (
    *_TASK12_RUNTIME_DATA_PATHS,
    "tests/fixtures/guide/final_release/"
    "real_translation_12x4_v5.jsonl",
    "tests/guide/tools/test_build_responsibility_matrix.py",
    "tests/guide/tools/test_final_real_translation.py",
    "tests/guide/tools/test_final_release_gate.py",
    "tests/guide/tools/test_record_manual_screenshot_review.py",
    "tests/guide/tools/test_replay_final_real_backend.py",
    "tools/guide_gates/attempt_ledger.py",
    "tools/guide_gates/build_responsibility_matrix.py",
    "tools/guide_gates/build_task11_readiness.py",
    "tools/guide_gates/record_manual_screenshot_review.py",
    "tools/guide_gates/replay_final_real_backend.py",
    "tools/guide_gates/run_bound_runtime.py",
    "tools/guide_gates/run_zero_api_runtime.py",
    "tools/guide_gates/runtime_auth.py",
    "tools/guide_gates/run_final_real_translation.py",
    "tools/guide_gates/run_final_release_gate.py",
    "tools/guide_gates/run_mainline_contract_browser_audit.py",
)
_FIXTURE_PATH_PATTERN = re.compile(
    r"tests/fixtures/guide/[A-Za-z0-9_./-]+"
)
_RELEASE_PLAN_PATHS = (
    "docs/superpowers/plans/2026-08-20-final-guide-release-closure.md",
    "docs/superpowers/plans/2026-08-21-guide-mainline-contract-closure.md",
)


def _canonical_candidate_manifest_path(
    root: Path,
    *,
    repair_epoch: int,
) -> Path:
    return (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / f"repair-epoch-{repair_epoch}"
        / "task11-candidate-manifest.json"
    ).resolve()


def _candidate_manifest_path_is_valid(
    path: Path,
    *,
    root: Path,
    repair_epoch: int,
    plan_revision: object,
) -> bool:
    canonical = _canonical_candidate_manifest_path(
        root,
        repair_epoch=repair_epoch,
    )
    if path.resolve() == canonical:
        return True
    revision_match = re.search(r"-(r\d+)$", str(plan_revision))
    if revision_match is None:
        return False
    expected = canonical.with_name(
        f"task11-candidate-manifest-{revision_match.group(1)}.json"
    )
    return path.resolve() == expected


def _candidate_artifact_suffix(manifest_path: Path) -> str:
    match = re.fullmatch(
        r"task11-candidate-manifest(?P<suffix>-r\d+)?\.json",
        manifest_path.name,
    )
    if match is None:
        raise Task11ReadinessError(
            "candidate manifest canonical path is invalid"
        )
    return str(match.group("suffix") or "")


def _candidate_readiness_path(manifest_path: Path) -> Path:
    suffix = _candidate_artifact_suffix(manifest_path)
    return manifest_path.with_name(
        f"task11-candidate-readiness{suffix}.json"
    )


class Task11ReadinessError(ValueError):
    pass


def _is_loopback_host(host: str | None) -> bool:
    if host == "localhost":
        return True
    if host is None:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _decode_base64url(
    value: object,
    *,
    length: int,
) -> bytes:
    if not isinstance(value, str) or not value:
        raise Task11ReadinessError("runtime provenance is invalid")
    try:
        decoded = base64.b64decode(
            value + ("=" * (-len(value) % 4)),
            altchars=b"-_",
            validate=True,
        )
    except (TypeError, ValueError) as exc:
        raise Task11ReadinessError(
            "runtime provenance is invalid"
        ) from exc
    canonical = (
        base64.urlsafe_b64encode(decoded)
        .decode("ascii")
        .rstrip("=")
    )
    if len(decoded) != length or canonical != value:
        raise Task11ReadinessError("runtime provenance is invalid")
    return decoded


def _verify_runtime_signature(
    *,
    public_key: object,
    signature: object,
    domain: bytes,
    payload: Mapping[str, object],
) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(
            _decode_base64url(public_key, length=32)
        ).verify(
            _decode_base64url(signature, length=64),
            domain + _canonical_bytes(dict(payload)),
        )
    except (InvalidSignature, ValueError) as exc:
        raise Task11ReadinessError(
            "runtime provenance is invalid"
        ) from exc


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


def _write_json_exclusive(
    path: Path,
    payload: dict[str, Any],
    *,
    label: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(_canonical_bytes(payload))
    except FileExistsError as exc:
        raise Task11ReadinessError(
            f"{label} already exists: {path}"
        ) from exc


def _require_readiness_parent_binding(
    *,
    parent_path: Path,
    parent_descriptor: int,
    parent_identity: tuple[int, int],
    manifest_name: str,
    expected_manifest_sha256: str,
) -> None:
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    visible_descriptor: int | None = None
    manifest_descriptor: int | None = None
    try:
        visible_descriptor = os.open(parent_path, directory_flags)
        opened_parent = os.fstat(parent_descriptor)
        visible_parent = os.fstat(visible_descriptor)
        manifest_descriptor = os.open(
            manifest_name,
            file_flags,
            dir_fd=parent_descriptor,
        )
        manifest_metadata = os.fstat(manifest_descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(manifest_descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError as exc:
        raise Task11ReadinessError(
            "candidate readiness parent changed"
        ) from exc
    finally:
        if manifest_descriptor is not None:
            os.close(manifest_descriptor)
        if visible_descriptor is not None:
            os.close(visible_descriptor)
    if (
        (opened_parent.st_dev, opened_parent.st_ino) != parent_identity
        or (visible_parent.st_dev, visible_parent.st_ino)
        != parent_identity
        or not stat.S_ISREG(manifest_metadata.st_mode)
        or manifest_metadata.st_uid != os.getuid()
        or manifest_metadata.st_nlink != 1
        or sha256(b"".join(chunks)).hexdigest()
        != expected_manifest_sha256
    ):
        raise Task11ReadinessError(
            "candidate readiness parent changed"
        )


def _require_readiness_publication_authority(
    *,
    parent_path: Path,
    parent_descriptor: int,
    parent_identity: tuple[int, int],
    manifest_name: str,
    expected_manifest_sha256: str,
    repo_root: Path,
    protected_paths: Sequence[str],
    protected_payload_sha256: str,
    fixture_runtime_private_key_path: Path,
    runtime_public_keys: tuple[str, str],
    selected_slot: int,
) -> None:
    _require_readiness_parent_binding(
        parent_path=parent_path,
        parent_descriptor=parent_descriptor,
        parent_identity=parent_identity,
        manifest_name=manifest_name,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if (
        canonical_payload_sha256(
            repo_root,
            tuple(protected_paths),
        )
        != protected_payload_sha256
    ):
        raise Task11ReadinessError("protected payload drift")
    _require_runtime_private_keys_destroyed(
        fixture_runtime_private_key_path,
        repo_root=repo_root,
        manifest_sha256=expected_manifest_sha256,
        runtime_public_keys=runtime_public_keys,
        selected_slot=selected_slot,
    )


def _write_readiness_exclusive(
    path: Path,
    payload: dict[str, Any],
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    parent_descriptor: int,
    parent_identity: tuple[int, int],
    repo_root: Path,
    protected_paths: Sequence[str],
    protected_payload_sha256: str,
    fixture_runtime_private_key_path: Path,
    runtime_public_keys: tuple[str, str],
    selected_slot: int,
) -> None:
    data = _canonical_bytes(payload)
    pending_name = f".{path.name}.pending"
    file_flags = (
        os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor: int | None = None

    try:
        try:
            final_metadata = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            final_metadata = None
        try:
            pending_metadata = os.stat(
                pending_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pending_metadata = None
        if final_metadata is not None:
            if pending_metadata is None:
                raise Task11ReadinessError(
                    f"candidate readiness already exists: {path}"
                )
            descriptor = os.open(
                pending_name,
                file_flags,
                dir_fd=parent_descriptor,
            )
            opened = os.fstat(descriptor)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.getuid()
                or opened.st_nlink != 2
                or not os.path.samestat(opened, pending_metadata)
                or not os.path.samestat(opened, final_metadata)
                or b"".join(chunks) != data
            ):
                raise Task11ReadinessError(
                    "candidate readiness recovery is invalid"
                )
            try:
                _require_readiness_publication_authority(
                    parent_path=path.parent,
                    parent_descriptor=parent_descriptor,
                    parent_identity=parent_identity,
                    manifest_name=manifest_path.name,
                    expected_manifest_sha256=expected_manifest_sha256,
                    repo_root=repo_root,
                    protected_paths=protected_paths,
                    protected_payload_sha256=protected_payload_sha256,
                    fixture_runtime_private_key_path=(
                        fixture_runtime_private_key_path
                    ),
                    runtime_public_keys=runtime_public_keys,
                    selected_slot=selected_slot,
                )
            except Task11ReadinessError:
                os.unlink(path.name, dir_fd=parent_descriptor)
                os.fsync(parent_descriptor)
                raise
            os.unlink(pending_name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
            final_after = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                final_after.st_nlink != 1
                or not os.path.samestat(opened, final_after)
            ):
                raise Task11ReadinessError(
                    "candidate readiness recovery is invalid"
                )
            _require_readiness_parent_binding(
                parent_path=path.parent,
                parent_descriptor=parent_descriptor,
                parent_identity=parent_identity,
                manifest_name=manifest_path.name,
                expected_manifest_sha256=expected_manifest_sha256,
            )
            return
        if pending_metadata is None:
            descriptor = os.open(
                pending_name,
                file_flags | os.O_CREAT | os.O_EXCL,
                0o644,
                dir_fd=parent_descriptor,
            )
            os.fchmod(descriptor, 0o644)
        else:
            descriptor = os.open(
                pending_name,
                file_flags,
                dir_fd=parent_descriptor,
            )
        opened = os.fstat(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        current = b"".join(chunks)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.getuid()
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o644
            or (
                pending_metadata is not None
                and not os.path.samestat(opened, pending_metadata)
            )
            or len(current) > len(data)
            or not data.startswith(current)
        ):
            raise Task11ReadinessError(
                "candidate readiness recovery is invalid"
            )
        os.lseek(descriptor, 0, os.SEEK_END)
        remaining = memoryview(data[len(current) :])
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("candidate readiness write failed")
            remaining = remaining[written:]
        os.fsync(descriptor)
        _require_readiness_publication_authority(
            parent_path=path.parent,
            parent_descriptor=parent_descriptor,
            parent_identity=parent_identity,
            manifest_name=manifest_path.name,
            expected_manifest_sha256=expected_manifest_sha256,
            repo_root=repo_root,
            protected_paths=protected_paths,
            protected_payload_sha256=protected_payload_sha256,
            fixture_runtime_private_key_path=(
                fixture_runtime_private_key_path
            ),
            runtime_public_keys=runtime_public_keys,
            selected_slot=selected_slot,
        )
        os.link(
            pending_name,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        linked_pending = os.fstat(descriptor)
        linked_final = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            linked_pending.st_nlink != 2
            or not os.path.samestat(linked_pending, linked_final)
        ):
            raise Task11ReadinessError(
                "candidate readiness publication is invalid"
            )
        try:
            _require_readiness_publication_authority(
                parent_path=path.parent,
                parent_descriptor=parent_descriptor,
                parent_identity=parent_identity,
                manifest_name=manifest_path.name,
                expected_manifest_sha256=expected_manifest_sha256,
                repo_root=repo_root,
                protected_paths=protected_paths,
                protected_payload_sha256=protected_payload_sha256,
                fixture_runtime_private_key_path=(
                    fixture_runtime_private_key_path
                ),
                runtime_public_keys=runtime_public_keys,
                selected_slot=selected_slot,
            )
        except Task11ReadinessError:
            os.unlink(path.name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
            raise
        os.fsync(parent_descriptor)
        os.unlink(pending_name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
        final_after = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            final_after.st_nlink != 1
            or not os.path.samestat(linked_pending, final_after)
        ):
            raise Task11ReadinessError(
                "candidate readiness publication is invalid"
            )
        _require_readiness_parent_binding(
            parent_path=path.parent,
            parent_descriptor=parent_descriptor,
            parent_identity=parent_identity,
            manifest_name=manifest_path.name,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    except FileExistsError as exc:
        raise Task11ReadinessError(
            f"candidate readiness already exists: {path}"
        ) from exc
    except OSError as exc:
        raise Task11ReadinessError(
            "candidate readiness could not be published"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _rollback_recoverable_readiness_link(
    *,
    path: Path,
    parent_descriptor: int,
) -> None:
    pending_name = f".{path.name}.pending"
    try:
        final_metadata = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        pending_metadata = os.stat(
            pending_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise Task11ReadinessError(
            "candidate readiness recovery is invalid"
        ) from exc
    if (
        final_metadata.st_nlink != 2
        or pending_metadata.st_nlink != 2
        or not os.path.samestat(final_metadata, pending_metadata)
    ):
        raise Task11ReadinessError(
            "candidate readiness recovery is invalid"
        )
    try:
        os.unlink(path.name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
    except OSError as exc:
        raise Task11ReadinessError(
            "candidate readiness recovery is invalid"
        ) from exc


def _write_private_json_exclusive(
    path: Path,
    payload: dict[str, Any],
) -> None:
    expanded = path.expanduser()
    if not expanded.is_absolute() or expanded.is_symlink():
        raise Task11ReadinessError(
            "fixture runtime private key path must be absolute"
        )
    resolved = expanded.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            resolved,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            raise Task11ReadinessError(
                "fixture runtime private key path is invalid"
            )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(_canonical_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise Task11ReadinessError(
            f"fixture runtime private key already exists: {resolved}"
        ) from exc
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        resolved.unlink(missing_ok=True)
        raise


def retry_runtime_private_key_path(path: str | Path) -> Path:
    primary = Path(path).expanduser()
    return primary.with_name(
        f"{primary.stem}.retry-2{primary.suffix}"
    )


def _runtime_public_keys(
    manifest: Mapping[str, object],
) -> tuple[str, str]:
    values = manifest.get("fixture_runtime_public_keys")
    if (
        not isinstance(values, list)
        or len(values) != _FIXTURE_RUNTIME_KEY_COUNT
        or any(not isinstance(value, str) for value in values)
        or len(set(values)) != _FIXTURE_RUNTIME_KEY_COUNT
    ):
        raise Task11ReadinessError("runtime provenance is invalid")
    for value in values:
        _decode_base64url(value, length=32)
    return str(values[0]), str(values[1])


def _manifest_runtime_private_key_paths(
    manifest: Mapping[str, object],
    *,
    repo_root: Path,
) -> tuple[Path, Path]:
    values = manifest.get("fixture_runtime_private_key_paths")
    if (
        not isinstance(values, list)
        or len(values) != _FIXTURE_RUNTIME_KEY_COUNT
        or any(not isinstance(value, str) for value in values)
    ):
        raise Task11ReadinessError(
            "runtime private key path binding is invalid"
        )
    primary = Path(values[0])
    expected = _runtime_private_key_paths(
        primary,
        repo_root=repo_root,
    )
    if tuple(str(path) for path in expected) != tuple(values):
        raise Task11ReadinessError(
            "runtime private key path binding is invalid"
        )
    return expected


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Task11ReadinessError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise Task11ReadinessError(f"{label} is invalid")
    return payload


def _read_regular_file_once(path: Path, *, label: str) -> bytes:
    candidate = path.absolute()
    current = Path(candidate.anchor)
    try:
        for component in candidate.parts[1:]:
            current /= component
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise Task11ReadinessError(
                    f"{label} path contains a symlink"
                )
    except OSError as exc:
        raise Task11ReadinessError(
            f"{label} is invalid"
        ) from exc

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
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.getuid()
            or opened.st_nlink != 1
        ):
            raise Task11ReadinessError(
                f"{label} is invalid"
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
        raise Task11ReadinessError(
            f"{label} is invalid"
        ) from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)
    if (
        not stat.S_ISREG(named.st_mode)
        or (opened.st_dev, opened.st_ino)
        != (after_read.st_dev, after_read.st_ino)
        or (opened.st_dev, opened.st_ino)
        != (named.st_dev, named.st_ino)
        or opened.st_size != after_read.st_size
        or opened.st_mtime_ns != after_read.st_mtime_ns
    ):
        raise Task11ReadinessError(
            f"{label} changed during read"
        )
    return b"".join(chunks)


def _read_manifest_once(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular_file_once(
        path,
        label="candidate manifest",
    )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Task11ReadinessError(
            "candidate manifest is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise Task11ReadinessError("candidate manifest is invalid")
    return payload, raw


def _bounded_call_string(
    call: ast.Call,
    keyword_name: str,
) -> str:
    matches = [
        keyword.value
        for keyword in call.keywords
        if keyword.arg == keyword_name
    ]
    if (
        len(matches) != 1
        or not isinstance(matches[0], ast.Constant)
        or not isinstance(matches[0].value, str)
    ):
        raise Task11ReadinessError(
            "browser bounded trajectory messages are invalid"
        )
    return matches[0].value


def _validate_bounded_trajectory_messages(
    *,
    repo_root: Path,
    cases_path: Path,
) -> tuple[tuple[str, str, str], ...]:
    try:
        rows = [
            json.loads(line)
            for line in cases_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Task11ReadinessError(
            "production matrix bounded trajectory messages are invalid"
        ) from exc
    matrix_messages: list[tuple[str, str, str]] = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("partition") != "bounded"
            or row.get("bounded") is not True
        ):
            continue
        trajectory_id = row.get("trajectory_id")
        case_id = row.get("case_id")
        message = row.get("message")
        if (
            not isinstance(trajectory_id, str)
            or not trajectory_id
            or not isinstance(case_id, str)
            or not case_id
            or not isinstance(message, str)
        ):
            raise Task11ReadinessError(
                "production matrix bounded trajectory messages are invalid"
            )
        matrix_messages.append((trajectory_id, case_id, message))

    browser_path = repo_root / _BOUNDED_BROWSER_TOOL_PATH
    try:
        browser_tree = ast.parse(
            browser_path.read_text(encoding="utf-8"),
            filename=str(browser_path),
        )
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise Task11ReadinessError(
            "browser bounded trajectory messages are invalid"
        ) from exc
    declarations = [
        statement.value
        for statement in browser_tree.body
        if isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "BOUNDED_TRAJECTORIES"
            for target in statement.targets
        )
    ]
    if (
        len(declarations) != 1
        or not isinstance(declarations[0], (ast.Tuple, ast.List))
    ):
        raise Task11ReadinessError(
            "browser bounded trajectory messages are invalid"
        )
    browser_messages: list[tuple[str, str, str]] = []
    for trajectory in declarations[0].elts:
        if not isinstance(trajectory, ast.Call):
            raise Task11ReadinessError(
                "browser bounded trajectory messages are invalid"
            )
        trajectory_id = _bounded_call_string(
            trajectory,
            "trajectory_id",
        )
        turns = [
            keyword.value
            for keyword in trajectory.keywords
            if keyword.arg == "turns"
        ]
        if (
            len(turns) != 1
            or not isinstance(turns[0], (ast.Tuple, ast.List))
        ):
            raise Task11ReadinessError(
                "browser bounded trajectory messages are invalid"
            )
        for turn in turns[0].elts:
            if not isinstance(turn, ast.Call):
                raise Task11ReadinessError(
                    "browser bounded trajectory messages are invalid"
                )
            turn_id = _bounded_call_string(turn, "turn_id")
            browser_messages.append(
                (
                    trajectory_id,
                    f"{trajectory_id}-{turn_id}",
                    _bounded_call_string(turn, "message"),
                )
            )
    matrix_contract = tuple(matrix_messages)
    browser_contract = tuple(browser_messages)
    if (
        len(matrix_contract) != _BOUNDED_TURN_COUNT
        or len({case_id for _, case_id, _ in matrix_contract})
        != _BOUNDED_TURN_COUNT
        or browser_contract != matrix_contract
    ):
        raise Task11ReadinessError(
            "production matrix and browser bounded trajectory messages differ"
        )
    return matrix_contract


def _normalized_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise Task11ReadinessError("candidate path escapes repository")
    return path.as_posix()


def parse_task11_files(
    plan_path: str | Path,
) -> dict[str, tuple[str, ...]]:
    text = Path(plan_path).read_text(encoding="utf-8")
    task_start = text.find("### Task 11:")
    task_end = text.find("### Task 12:", task_start + 1)
    if task_start < 0:
        raise Task11ReadinessError("Task 11 section is missing")
    if task_end < 0:
        task_end = len(text)
    task = text[task_start:task_end]
    files_start = task.find("**Files:**")
    first_step = task.find("- [", files_start)
    if files_start < 0 or first_step < 0:
        raise Task11ReadinessError("Task 11 Files block is missing")
    rows = _FILE_LINE_PATTERN.findall(task[files_start:first_step])
    if not rows:
        raise Task11ReadinessError("Task 11 Files block is empty")
    output: dict[str, list[str]] = {
        "source_paths": [],
        "test_paths": [],
        "tool_paths": [],
        "plan_paths": [],
        "fixture_paths": [],
        "deleted_paths": [],
        "generated_paths": [],
    }
    for action, raw_path in rows:
        path = _normalized_path(raw_path)
        if action == "Delete":
            key = "deleted_paths"
        elif (
            action == "Generate"
            or path.startswith(
                "docs/audits/final-release/"
                "mainline-contract-closure/"
            )
        ):
            key = "generated_paths"
        elif path.startswith("tests/fixtures/"):
            key = "fixture_paths"
        elif path.startswith("tests/"):
            key = "test_paths"
        elif path.startswith("tools/"):
            key = "tool_paths"
        elif path.startswith("docs/superpowers/plans/"):
            key = "plan_paths"
        else:
            key = "source_paths"
        if path in output[key]:
            raise Task11ReadinessError(
                f"duplicate Task 11 file path: {path}"
            )
        output[key].append(path)
    return {
        key: tuple(sorted(values))
        for key, values in output.items()
    }


def _fixture_dependencies_in_python(
    path: Path,
    *,
    repo_root: Path,
) -> tuple[str, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise Task11ReadinessError(
            f"cannot inspect test fixture dependencies: {path}"
        ) from exc
    dependencies = {
        dependency
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        for match in _FIXTURE_PATH_PATTERN.finditer(node.value)
        if (
            dependency := match.group(0).rstrip("./")
        )
        and (repo_root / dependency).is_file()
    }

    path_bindings: dict[str, tuple[str, ...]] = {}

    def literal_path_parts(node: ast.AST) -> tuple[str, ...]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return (node.value,)
        if isinstance(node, ast.Name):
            return path_bindings.get(node.id, ())
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return (
                *literal_path_parts(node.left),
                *literal_path_parts(node.right),
            )
        return ()

    for statement in tree.body:
        target: ast.Name | None = None
        value: ast.AST | None = None
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
        parts = literal_path_parts(value)
        if parts:
            path_bindings[target.id] = parts

    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        parts = literal_path_parts(node)
        if not parts or "fixtures" not in parts:
            continue
        fixture_index = parts.index("fixtures")
        candidate_parts = parts[fixture_index:]
        if (
            fixture_index == 0
            or parts[fixture_index - 1] != "tests"
        ):
            candidate_parts = ("tests", *candidate_parts)
        else:
            candidate_parts = parts[fixture_index - 1:]
        dependency = PurePosixPath(*candidate_parts).as_posix()
        if (
            dependency.startswith("tests/fixtures/guide/")
            and (repo_root / dependency).is_file()
        ):
            dependencies.add(dependency)
    return tuple(sorted(dependencies))


def _collected_test_nodeids(
    *,
    repo_root: Path,
    test_paths: Sequence[str],
) -> tuple[str, ...]:
    environment = dict(os.environ)
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{repo_root}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(repo_root)
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *test_paths,
        ],
        cwd=repo_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 5}:
        raise Task11ReadinessError(
            "Task 11 pytest node collection failed: "
            + completed.stderr.strip()
        )
    return tuple(
        line.strip()
        for line in completed.stdout.splitlines()
        if "::" in line
        and line.strip().split("::", 1)[0] in set(test_paths)
    )


def _production_matrix_inventory(
    *,
    repo_root: Path,
    fixture_dependencies: set[str],
) -> dict[str, int]:
    relative = (
        "tests/fixtures/guide/intent/"
        "task11_production_path_matrix_v1.jsonl"
    )
    if relative not in fixture_dependencies:
        raise Task11ReadinessError(
            "production-path fixture dependency is missing"
        )
    try:
        rows = [
            json.loads(line)
            for line in (repo_root / relative).read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise Task11ReadinessError(
            "production-path fixture is invalid"
        ) from exc
    if not all(isinstance(row, dict) for row in rows):
        raise Task11ReadinessError(
            "production-path fixture is invalid"
        )
    stateful = [
        row
        for row in rows
        if row.get("partition") in {"state", "bounded"}
    ]
    pre_decision_rejections = [
        row
        for row in rows
        if row.get("partition") == "pre_decision_rejection"
    ]
    if (
        len(rows) != _PRODUCTION_MATRIX_TURN_COUNT
        or len(pre_decision_rejections)
        != _PRE_DECISION_REJECTION_COUNT
    ):
        raise Task11ReadinessError(
            "production-path fixture must cover pre-decision rejection"
        )
    required_edges = {
        edge
        for row in stateful
        for edge in row.get("required_state_edges", [])
        if isinstance(edge, str) and edge
    }
    return {
        "case_count": len(rows),
        "trajectory_count": len({
            row.get("trajectory_id") for row in stateful
        }),
        "turn_count": len(rows),
        "state_edge_count": len(required_edges),
        "pre_decision_rejection_count": len(
            pre_decision_rejections
        ),
    }


def _assignment_target_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {
            name
            for item in node.elts
            for name in _assignment_target_names(item)
        }
    return set()


def _test_static_truth(value: ast.expr) -> bool | None:
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not):
        operand = _test_static_truth(value.operand)
        return None if operand is None else not operand
    if isinstance(value, ast.BoolOp):
        truths = tuple(_test_static_truth(item) for item in value.values)
        if isinstance(value.op, ast.And):
            if False in truths:
                return False
            return True if all(item is True for item in truths) else None
        if True in truths:
            return True
        return False if all(item is False for item in truths) else None
    try:
        return bool(ast.literal_eval(value))
    except (TypeError, ValueError):
        return None


def _test_statements_guaranteed_to_terminate(
    statements: Sequence[ast.stmt],
) -> bool:
    return any(
        _test_statement_guaranteed_to_terminate(statement)
        for statement in statements
    )


def _test_statement_guaranteed_to_terminate(
    statement: ast.stmt,
) -> bool:
    if isinstance(statement, (ast.Raise, ast.Return)):
        return True
    if isinstance(statement, ast.Assert):
        return _test_static_truth(statement.test) is False
    if isinstance(statement, (ast.Try, ast.TryStar)):
        if _test_statements_guaranteed_to_terminate(
            statement.finalbody
        ):
            return True
        normal_path_terminates = (
            _test_statements_guaranteed_to_terminate(statement.body)
            or (
                bool(statement.orelse)
                and _test_statements_guaranteed_to_terminate(
                    statement.orelse
                )
            )
        )
        exception_paths_terminate = (
            not statement.handlers
            or all(
                _test_statements_guaranteed_to_terminate(handler.body)
                for handler in statement.handlers
            )
        )
        return normal_path_terminates and exception_paths_terminate
    if not isinstance(statement, ast.If):
        return False
    truth = _test_static_truth(statement.test)
    if truth is True:
        return _test_statements_guaranteed_to_terminate(statement.body)
    if truth is False:
        return _test_statements_guaranteed_to_terminate(statement.orelse)
    return bool(statement.orelse) and all(
        _test_statements_guaranteed_to_terminate(branch)
        for branch in (statement.body, statement.orelse)
    )


def _asserts_runner_result_passed(
    statement: ast.stmt,
    result_name: str,
) -> bool:
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


def _is_safe_runner_result_assertion(
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


def _is_provider_env_cleanup(statement: ast.stmt) -> bool:
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


def _production_path_test_executes_runner(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise Task11ReadinessError(
            f"cannot inspect production-path test body: {path}"
        ) from exc
    runner_aliases: set[str] = set()
    invalid_aliases: set[str] = set()
    for statement in tree.body:
        if (
            isinstance(statement, ast.ImportFrom)
            and statement.module
            == "tools.guide_gates.run_task11_production_path_matrix"
        ):
            runner_aliases.update(
                alias.asname or alias.name
                for alias in statement.names
                if alias.name == "run_production_path_matrix"
            )
            continue
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            invalid_aliases.add(statement.name)
        elif isinstance(statement, ast.ClassDef):
            invalid_aliases.add(statement.name)
        elif isinstance(statement, ast.Assign):
            invalid_aliases.update(
                name
                for target in statement.targets
                for name in _assignment_target_names(target)
            )
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
            invalid_aliases.update(
                _assignment_target_names(statement.target)
            )
        elif isinstance(statement, ast.Import):
            invalid_aliases.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in statement.names
            )
        elif isinstance(statement, ast.ImportFrom):
            invalid_aliases.update(
                alias.asname or alias.name
                for alias in statement.names
                if alias.name != "*"
            )
    runner_aliases -= invalid_aliases
    tests = [
        statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name
        == "test_frozen_matrix_runs_full_http_production_path"
    ]
    if len(tests) != 1 or len(runner_aliases) != 1:
        return False
    test = tests[0]
    local_bindings = {
        node.id
        for node in ast.walk(test)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    runner_name = next(iter(runner_aliases))
    if runner_name in local_bindings:
        return False
    all_runner_calls = tuple(
        node
        for node in ast.walk(test)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == runner_name
    )
    if len(all_runner_calls) != 1:
        return False
    result_names: set[str] = set()
    call_count = 0
    result_asserted = False
    for statement in test.body:
        value = (
            statement.value
            if isinstance(statement, (ast.Assign, ast.AnnAssign))
            else None
        )
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == runner_name
        ):
            if (
                not result_names
                and call_count == 0
                and _is_provider_env_cleanup(statement)
            ):
                continue
            if (
                result_names
                and _is_safe_runner_result_assertion(
                    statement,
                    next(iter(result_names)),
                )
            ):
                result_asserted = (
                    result_asserted
                    or _asserts_runner_result_passed(
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
        call_count += 1
        if isinstance(statement, ast.Assign):
            result_names.update(
                name
                for target in statement.targets
                for name in _assignment_target_names(target)
            )
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
        ):
            result_names.add(statement.target.id)
    if call_count != 1 or len(result_names) != 1 or not result_asserted:
        return False
    result_name = next(iter(result_names))
    return (
        sum(
            1
            for node in ast.walk(test)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id == result_name
        )
        == 1
    )


_FRONTEND_FIXTURE_CALLS = frozenset({
    "fixture_sse_bytes",
    "run_fixture_browser_audit",
    "run_fixture_browser_audits",
})
_LAYER_BOUNDARY_CALLS = frozenset({
    "TestClient",
    "compile_turn_meaning",
    "reduce_conversation_state",
    "route_unified_turn",
})
_GUIDE_LAYER_PREFIXES = (
    ("app.guide.adapters", "adapters"),
    ("app.guide.application", "application"),
    ("app.guide.decision", "decision"),
    ("app.guide.feedback", "feedback"),
    ("app.guide.intent", "intent"),
    ("app.guide.presentation", "presentation"),
    ("app.guide.retrieval", "retrieval"),
    ("app.guide.understanding", "understanding"),
    ("app.guide_runtime", "runtime"),
)


def _call_leaf_name(call: ast.Call) -> str | None:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _module_import_bindings(tree: ast.Module) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                bindings[alias.asname or alias.name.split(".", 1)[0]] = (
                    alias.name
                )
        elif isinstance(statement, ast.ImportFrom):
            if statement.module is None:
                continue
            for alias in statement.names:
                bindings[alias.asname or alias.name] = (
                    f"{statement.module}.{alias.name}"
                )
    return bindings


def _module_value_bindings(tree: ast.Module) -> dict[str, ast.AST]:
    bindings: dict[str, ast.AST] = {}
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            value = statement.value
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else (statement.target,)
            )
            for target in targets:
                if isinstance(target, ast.Name) and value is not None:
                    bindings[target.id] = value
    return bindings


def _test_function_nodes(
    tree: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def visit(statements: Sequence[ast.stmt], prefix: tuple[str, ...]) -> None:
        for statement in statements:
            if isinstance(statement, ast.ClassDef):
                visit(statement.body, (*prefix, statement.name))
            elif isinstance(
                statement,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ) and statement.name.startswith("test"):
                functions["::".join((*prefix, statement.name))] = statement

    visit(tree.body, ())
    return functions


def _reachable_test_nodes(
    tree: ast.Module,
    test: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[ast.AST, ...]:
    helpers = {
        statement.name: statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not statement.name.startswith("test")
    }
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
                and node.func.id in helpers
            ):
                pending.append(helpers[node.func.id])
    return tuple(reached)


def _literal_path_parts(
    node: ast.AST,
    *,
    bindings: Mapping[str, ast.AST],
) -> tuple[str, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.Name):
        bound = bindings.get(node.id)
        return (
            _literal_path_parts(bound, bindings=bindings)
            if bound is not None
            else ()
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return (
            *_literal_path_parts(node.left, bindings=bindings),
            *_literal_path_parts(node.right, bindings=bindings),
        )
    return ()


def _fixture_paths_from_nodes(
    nodes: Sequence[ast.AST],
    *,
    bindings: Mapping[str, ast.AST],
    repo_root: Path,
) -> set[str]:
    dependencies = {
        dependency
        for root in nodes
        for node in ast.walk(root)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        for match in _FIXTURE_PATH_PATTERN.finditer(node.value)
        if (dependency := match.group(0).rstrip("./"))
        and (repo_root / dependency).is_file()
    }
    for root in nodes:
        for node in ast.walk(root):
            if (
                not isinstance(node, ast.BinOp)
                or not isinstance(node.op, ast.Div)
            ):
                continue
            parts = _literal_path_parts(node, bindings=bindings)
            if not parts or "fixtures" not in parts:
                continue
            fixture_index = parts.index("fixtures")
            candidate_parts = parts[fixture_index:]
            if (
                fixture_index == 0
                or parts[fixture_index - 1] != "tests"
            ):
                candidate_parts = ("tests", *candidate_parts)
            else:
                candidate_parts = parts[fixture_index - 1:]
            dependency = PurePosixPath(*candidate_parts).as_posix()
            if (
                dependency.startswith("tests/fixtures/guide/")
                and (repo_root / dependency).is_file()
            ):
                dependencies.add(dependency)
    return dependencies


def _fixture_dependencies_for_test_node(
    *,
    tree: ast.Module,
    nodeid: str,
    repo_root: Path,
) -> tuple[str, ...]:
    node_path = nodeid.split("::", 1)[1]
    node_parts = node_path.split("::")
    node_parts[-1] = node_parts[-1].split("[", 1)[0]
    test = _test_function_nodes(tree).get("::".join(node_parts))
    if test is None:
        raise Task11ReadinessError(
            f"collected test function is missing: {nodeid}"
        )
    reached = _reachable_test_nodes(tree, test)
    local_bindings = _module_value_bindings(tree)
    loaded_names = {
        node.id
        for root in reached
        for node in ast.walk(root)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    referenced_values = tuple(
        local_bindings[name]
        for name in loaded_names
        if name in local_bindings
    )
    dependencies = _fixture_paths_from_nodes(
        (*reached, *referenced_values),
        bindings=local_bindings,
        repo_root=repo_root,
    )
    import_bindings = _module_import_bindings(tree)
    for name in sorted(loaded_names):
        imported = import_bindings.get(name)
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
                module_path.read_text(encoding="utf-8"),
                filename=str(module_path),
            )
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Task11ReadinessError(
                f"cannot inspect imported fixture dependency: {imported}"
            ) from exc
        imported_values = _module_value_bindings(imported_tree)
        imported_value = imported_values.get(symbol)
        if imported_value is None:
            continue
        dependencies.update(
            _fixture_paths_from_nodes(
                (imported_value,),
                bindings=imported_values,
                repo_root=repo_root,
            )
        )
    return tuple(sorted(dependencies))


def _derived_test_scope(
    *,
    tree: ast.Module,
    nodeid: str,
) -> tuple[str, str, list[str], list[str], str]:
    node_path = nodeid.split("::", 1)[1]
    node_parts = node_path.split("::")
    node_parts[-1] = node_parts[-1].split("[", 1)[0]
    test_key = "::".join(node_parts)
    test = _test_function_nodes(tree).get(test_key)
    if test is None:
        raise Task11ReadinessError(
            f"collected test function is missing: {nodeid}"
        )
    nodes = _reachable_test_nodes(tree, test)
    calls = {
        leaf
        for root in nodes
        for node in ast.walk(root)
        if isinstance(node, ast.Call)
        and (leaf := _call_leaf_name(node)) is not None
    }
    loaded_names = {
        node.id
        for root in nodes
        for node in ast.walk(root)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    values = _module_value_bindings(tree)
    referenced_values = [
        values[name] for name in loaded_names if name in values
    ]
    strings = {
        node.value
        for root in (*nodes, *referenced_values)
        for node in ast.walk(root)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
    }
    import_bindings = _module_import_bindings(tree)
    used_modules = {
        module
        for name, module in import_bindings.items()
        if name in loaded_names
    }
    frontend_fixture = (
        bool(calls & _FRONTEND_FIXTURE_CALLS)
        or any(module.startswith("playwright") for module in used_modules)
        or any(
            value.startswith("event: ")
            or value.endswith((".sse", "chat.html", "guide-presentation.js"))
            or value.startswith("app/static/")
            for value in strings
        )
    )
    guide_layers = {
        layer
        for module in used_modules
        for prefix, layer in _GUIDE_LAYER_PREFIXES
        if module == prefix or module.startswith(f"{prefix}.")
    }
    layer_contract = (
        bool(calls & _LAYER_BOUNDARY_CALLS)
        or any(
            module in {"fastapi.testclient", "starlette.testclient"}
            for module in used_modules
        )
        or any(value.startswith("/api/") for value in strings)
        or len(guide_layers) >= 2
    )
    if frontend_fixture:
        return (
            "frontend_fixture",
            "prebuilt_frontend_fixture",
            ["typed_sse_fixture", "frontend_renderer"],
            ["live_backend", "http_production_path"],
            "prebuilt_typed_sse",
        )
    if layer_contract:
        return (
            "layer_contract",
            "direct_layer_boundary",
            sorted(guide_layers) or ["declared_layer_boundary"],
            ["full_http_production_path"],
            "direct_contract_or_component",
        )
    return (
        "unit",
        "direct_component_api",
        ["isolated_component"],
        ["http_production_path", "cross_layer_integration"],
        "direct_value_or_component",
    )


def build_test_path_audit(
    *,
    repo_root: str | Path,
    plan_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    parsed = parse_task11_files(plan_path)
    fixture_dependencies = set(parsed["fixture_paths"])
    test_trees: dict[str, ast.Module] = {}
    for test_path in parsed["test_paths"]:
        path = root / test_path
        if not path.is_file():
            raise Task11ReadinessError(
                f"Task 11 test path is missing: {test_path}"
            )
        try:
            test_trees[test_path] = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
            )
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Task11ReadinessError(
                f"Task 11 test path is invalid: {test_path}"
            ) from exc
    nodeids = _collected_test_nodeids(
        repo_root=root,
        test_paths=parsed["test_paths"],
    )
    fixture_dependencies_by_node = {
        nodeid: _fixture_dependencies_for_test_node(
            tree=test_trees[nodeid.split("::", 1)[0]],
            nodeid=nodeid,
            repo_root=root,
        )
        for nodeid in nodeids
    }
    for dependencies in fixture_dependencies_by_node.values():
        fixture_dependencies.update(dependencies)
    production_node = (
        "tests/guide/tools/test_task11_production_path_matrix.py::"
        "test_frozen_matrix_runs_full_http_production_path"
    )
    production_test_path = (
        root / production_node.split("::", 1)[0]
    )
    if (
        any(nodeid.split("[", 1)[0] == production_node for nodeid in nodeids)
        and not _production_path_test_executes_runner(production_test_path)
    ):
        raise Task11ReadinessError(
            "production-path test body is invalid"
        )
    matrix_counts = _production_matrix_inventory(
        repo_root=root,
        fixture_dependencies=fixture_dependencies,
    )
    gates: list[dict[str, Any]] = []
    for nodeid in nodeids:
        test_path = nodeid.split("::", 1)[0]
        dependencies = fixture_dependencies_by_node[nodeid]
        if nodeid.split("[", 1)[0] == production_node:
            gate = nodeid
            claimed_scope = "production_path_from_turn_meaning"
            real_entrypoint = "/api/v1/chat/stream"
            layers_executed = list(_RUNTIME_LAYER_ORDER)
            layers_bypassed: list[str] = []
            semantic_injection_type = "frozen_turn_meaning_provider"
            runtime_evidence_source = (
                "task11-production-path-summary"
            )
            case_count = matrix_counts["case_count"]
            trajectory_count = matrix_counts["trajectory_count"]
            turn_count = matrix_counts["turn_count"]
            state_edge_count = matrix_counts["state_edge_count"]
            pre_decision_rejection_count = (
                matrix_counts["pre_decision_rejection_count"]
            )
        else:
            gate = nodeid
            (
                claimed_scope,
                real_entrypoint,
                layers_executed,
                layers_bypassed,
                semantic_injection_type,
            ) = _derived_test_scope(
                tree=test_trees[test_path],
                nodeid=nodeid,
            )
            runtime_evidence_source = None
            case_count = 0
            trajectory_count = 0
            turn_count = 0
            state_edge_count = 0
            pre_decision_rejection_count = 0
        gates.append({
            "gate": gate,
            "claimed_scope": claimed_scope,
            "real_entrypoint": real_entrypoint,
            "layers_executed": layers_executed,
            "layers_bypassed": layers_bypassed,
            "semantic_injection_type": semantic_injection_type,
            "runtime_evidence_source": runtime_evidence_source,
            "test_files": [test_path],
            "fixture_files": list(dependencies),
            "case_count": case_count,
            "trajectory_count": trajectory_count,
            "turn_count": turn_count,
            "state_edge_count": state_edge_count,
            "pre_decision_rejection_count": (
                pre_decision_rejection_count
            ),
        })
    missing_fixtures = sorted(
        path
        for path in fixture_dependencies
        if not (root / path).is_file()
    )
    production_count = sum(
        gate["claimed_scope"]
        == "production_path_from_turn_meaning"
        for gate in gates
    )
    invalid_claims = sum(
        gate["claimed_scope"]
        == "production_path_from_turn_meaning"
        and (
            gate["real_entrypoint"] != "/api/v1/chat/stream"
            or gate["layers_bypassed"]
            or gate["semantic_injection_type"]
            != "frozen_turn_meaning_provider"
        )
        for gate in gates
    )
    scope_counts = {
        scope: sum(
            gate["claimed_scope"] == scope
            for gate in gates
        )
        for scope in (
            "unit",
            "layer_contract",
            "frontend_fixture",
            "production_path_from_turn_meaning",
        )
    }
    audit = {
        "schema_version": "guide-task11-test-path-audit-v1",
        "passed": (
            production_count == 1
            and invalid_claims == 0
            and not missing_fixtures
            and {
                gate["claimed_scope"]
                for gate in gates
                if gate["claimed_scope"]
                != "production_path_from_turn_meaning"
            }
            != {"layer_contract"}
        ),
        "production_path_gate_count": production_count,
        "scope_counts": scope_counts,
        "invalid_production_path_claim_count": invalid_claims,
        "unprotected_fixture_dependency_count": len(
            missing_fixtures
        ),
        "fixture_dependencies": sorted(fixture_dependencies),
        "missing_fixture_dependencies": missing_fixtures,
        "gates": gates,
    }
    _write_json_exclusive(
        Path(output_path),
        audit,
        label="test path audit",
    )
    if audit["passed"] is not True:
        raise Task11ReadinessError("test path audit failed")
    return audit


def canonical_payload_sha256(
    repo_root: str | Path,
    paths: Sequence[str],
) -> str:
    root = Path(repo_root).absolute()
    directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    file_flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        root_descriptor = os.open(root, directory_flags)
    except OSError as exc:
        raise Task11ReadinessError(
            "candidate repository root is invalid"
        ) from exc
    digest = sha256()
    try:
        opened_root = os.fstat(root_descriptor)
        if (
            not stat.S_ISDIR(opened_root.st_mode)
            or opened_root.st_uid != os.getuid()
        ):
            raise Task11ReadinessError(
                "candidate repository root is invalid"
            )
        for raw_path in sorted(paths):
            relative = _normalized_path(raw_path)
            components = PurePosixPath(relative).parts
            directory_descriptors = [os.dup(root_descriptor)]
            ancestor_components: list[str] = []
            file_descriptor: int | None = None
            try:
                for component in components[:-1]:
                    next_descriptor = os.open(
                        component,
                        directory_flags,
                        dir_fd=directory_descriptors[-1],
                    )
                    opened_ancestor = os.fstat(next_descriptor)
                    named_ancestor = os.stat(
                        component,
                        dir_fd=directory_descriptors[-1],
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
                        os.close(next_descriptor)
                        raise Task11ReadinessError(
                            f"candidate ancestor changed: {relative}"
                        )
                    directory_descriptors.append(next_descriptor)
                    ancestor_components.append(component)
                file_descriptor = os.open(
                    components[-1],
                    file_flags,
                    dir_fd=directory_descriptors[-1],
                )
                opened = os.fstat(file_descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_uid != os.getuid()
                    or opened.st_nlink != 1
                ):
                    raise Task11ReadinessError(
                        f"candidate path is invalid: {relative}"
                    )
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(file_descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after_read = os.fstat(file_descriptor)
                named = os.stat(
                    components[-1],
                    dir_fd=directory_descriptors[-1],
                    follow_symlinks=False,
                )
                for index, component in enumerate(ancestor_components):
                    opened_ancestor = os.fstat(
                        directory_descriptors[index + 1]
                    )
                    named_ancestor = os.stat(
                        component,
                        dir_fd=directory_descriptors[index],
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
                        raise Task11ReadinessError(
                            f"candidate ancestor changed: {relative}"
                        )
            except OSError as exc:
                raise Task11ReadinessError(
                    f"candidate path is invalid: {relative}"
                ) from exc
            finally:
                if file_descriptor is not None:
                    os.close(file_descriptor)
                for descriptor in reversed(directory_descriptors):
                    os.close(descriptor)
            if (
                not stat.S_ISREG(named.st_mode)
                or (opened.st_dev, opened.st_ino)
                != (after_read.st_dev, after_read.st_ino)
                or (opened.st_dev, opened.st_ino)
                != (named.st_dev, named.st_ino)
                or opened.st_size != after_read.st_size
                or opened.st_mtime_ns != after_read.st_mtime_ns
            ):
                raise Task11ReadinessError(
                    f"candidate path changed during read: {relative}"
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
            visible_root = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise Task11ReadinessError(
                "repository root changed during payload hash"
            ) from exc
        if (
            not stat.S_ISDIR(visible_root.st_mode)
            or (opened_root.st_dev, opened_root.st_ino)
            != (visible_root.st_dev, visible_root.st_ino)
        ):
            raise Task11ReadinessError(
                "repository root changed during payload hash"
            )
        return digest.hexdigest()
    finally:
        os.close(root_descriptor)


def _is_excluded(path: str) -> bool:
    if path in {
        (
            "docs/superpowers/plans/"
            "2026-08-20-recording-ready-guide-path.md"
        ),
    }:
        return True
    if path.startswith(
        (
            ".dbg/",
            ".tmp-",
            "docs/audits/continuous-conversation/",
            (
                "docs/audits/final-release/"
                "mainline-contract-closure/"
            ),
        )
    ):
        return True
    return (
        path.startswith("debug-")
        and path.endswith(".md")
    )


def _is_relevant(path: str) -> bool:
    return path in _RELEVANT_ROOT_FILES or any(
        path == prefix.rstrip("/") or path.startswith(prefix)
        for prefix in _RELEVANT_PREFIXES
    )


def discover_relevant_changes(repo_root: str | Path) -> tuple[str, ...]:
    root = Path(repo_root).resolve()
    completed = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[str] = []
    for line in completed.stdout.splitlines():
        if len(line) < 4:
            continue
        value = line[3:]
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        path = _normalized_path(value)
        if _is_relevant(path) and not _is_excluded(path):
            paths.append(path)
    return tuple(sorted(set(paths)))


def _plan_revision(plan_path: Path) -> str:
    match = _PLAN_REVISION_PATTERN.search(
        plan_path.read_text(encoding="utf-8")
    )
    if match is None:
        raise Task11ReadinessError("plan revision is missing")
    return match.group(1)


def _task11_evidence_epoch(plan_path: Path) -> int:
    match = _TASK11_EPOCH_PATTERN.search(
        plan_path.read_text(encoding="utf-8")
    )
    if match is None:
        raise Task11ReadinessError("Task 11 evidence epoch is missing")
    epoch = int(match.group(1))
    if epoch < 1:
        raise Task11ReadinessError("Task 11 evidence epoch is invalid")
    return epoch


def _git_head(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_top_level(repo_root: Path) -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise Task11ReadinessError(
            "candidate repository root is invalid"
        )
    top_level = Path(completed.stdout.strip()).resolve()
    if top_level != repo_root.resolve():
        raise Task11ReadinessError(
            "candidate repository root is invalid"
        )
    return top_level


def _git_blob(
    repo_root: Path,
    *,
    revision: str,
    path: str,
) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise Task11ReadinessError(
            f"deleted base blob is missing: {path}"
        )
    return completed.stdout


def _candidate_diff_sha256(
    root: Path,
    *,
    revision: str,
    change_paths: Sequence[str],
) -> str:
    digest = sha256()
    for relative in sorted(change_paths):
        base_result = subprocess.run(
            ["git", "show", f"{revision}:{relative}"],
            cwd=root,
            check=False,
            capture_output=True,
        )
        base = (
            base_result.stdout if base_result.returncode == 0 else None
        )
        current_path = root / relative
        if current_path.is_symlink():
            raise Task11ReadinessError(
                f"candidate change path is a symlink: {relative}"
            )
        current = current_path.read_bytes() if current_path.is_file() else None
        if base is None and current is not None:
            status = b"A"
        elif base is not None and current is None:
            status = b"D"
        elif base is not None and current is not None and base != current:
            status = b"M"
        else:
            raise Task11ReadinessError(
                f"candidate change path has no diff: {relative}"
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


def build_candidate_manifest(
    *,
    repo_root: str | Path,
    plan_path: str | Path,
    output_path: str | Path,
    candidate_head: str | None = None,
    changed_paths: Sequence[str] | None = None,
    test_path_audit_path: str | Path | None = None,
    fixture_runtime_private_key_path: str | Path | None = None,
    _fixture_runtime_private_key: Ed25519PrivateKey | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    _git_top_level(root)
    plan = Path(plan_path).resolve()
    try:
        plan_relative = plan.relative_to(root).as_posix()
    except ValueError as exc:
        raise Task11ReadinessError(
            "plan path must be inside repository"
        ) from exc
    parsed = parse_task11_files(plan)
    repair_epoch = _task11_evidence_epoch(plan)
    plan_revision = _plan_revision(plan)
    output = Path(output_path).resolve()
    if not _candidate_manifest_path_is_valid(
        output,
        root=root,
        repair_epoch=repair_epoch,
        plan_revision=plan_revision,
    ):
        raise Task11ReadinessError(
            "candidate manifest canonical path is invalid"
        )
    fixture_paths = set(parsed["fixture_paths"])
    if test_path_audit_path is not None:
        test_path_audit = _read_object(
            Path(test_path_audit_path),
            label="test path audit",
        )
        if (
            test_path_audit.get("schema_version")
            != "guide-task11-test-path-audit-v1"
            or test_path_audit.get("passed") is not True
            or not isinstance(
                test_path_audit.get("fixture_dependencies"),
                list,
            )
        ):
            raise Task11ReadinessError("test path audit is invalid")
        fixture_paths.update(
            _normalized_path(str(path))
            for path in test_path_audit["fixture_dependencies"]
        )
    protected = tuple(
        sorted(
            {
                *parsed["source_paths"],
                *parsed["test_paths"],
                *parsed["tool_paths"],
                *parsed["plan_paths"],
                *fixture_paths,
            }
        )
    )
    missing_static_dependencies = tuple(
        path
        for path in _required_local_static_dependencies(root, protected)
        if path not in protected
    )
    if missing_static_dependencies:
        raise Task11ReadinessError(
            "local static dependencies missing from Task 11 Files: "
            + ", ".join(missing_static_dependencies)
        )
    deleted = tuple(sorted(parsed["deleted_paths"]))
    existing_deleted = tuple(
        path for path in deleted if (root / path).exists()
    )
    if existing_deleted:
        raise Task11ReadinessError(
            "planned deleted paths still exist: "
            + ", ".join(existing_deleted)
        )
    if plan_relative not in protected:
        raise Task11ReadinessError(
            "active plan is missing from Task 11 Files"
        )
    changed = tuple(
        sorted(
            _normalized_path(path)
            for path in (
                discover_relevant_changes(root)
                if changed_paths is None
                else changed_paths
            )
            if not _is_excluded(path)
        )
    )
    approved_changes = {*protected, *deleted}
    missing = tuple(
        path for path in changed if path not in approved_changes
    )
    if missing:
        raise Task11ReadinessError(
            "relevant changed paths missing from Task 11 Files: "
            + ", ".join(missing)
        )
    missing_deletions = tuple(
        path for path in deleted if path not in changed
    )
    if missing_deletions:
        raise Task11ReadinessError(
            "planned deletions missing from candidate changes: "
            + ", ".join(missing_deletions)
        )
    head = candidate_head or _git_head(root)
    if _HEX_40_PATTERN.fullmatch(head) is None:
        raise Task11ReadinessError("candidate HEAD is invalid")
    deleted_hashes = {
        path: sha256(
            _git_blob(root, revision=head, path=path)
        ).hexdigest()
        for path in deleted
    }
    payload_sha256 = canonical_payload_sha256(root, protected)
    generated_private_key, generated_public_key = (
        generate_runtime_keypair()
        if _fixture_runtime_private_key is None
        else (
            _fixture_runtime_private_key,
            runtime_public_key(_fixture_runtime_private_key),
        )
    )
    retry_private_key, retry_public_key = generate_runtime_keypair()
    if retry_public_key == generated_public_key:
        raise Task11ReadinessError(
            "fixture runtime public keys must be distinct"
        )
    if fixture_runtime_private_key_path is None:
        raise Task11ReadinessError(
            "fixture runtime private key path is required"
        )
    private_key_file = Path(
        fixture_runtime_private_key_path
    ).expanduser()
    private_key_files = _runtime_private_key_paths(
        private_key_file,
        repo_root=root,
    )
    ledger_path = (root / _MUTABLE_EVIDENCE_PATHS[0]).resolve()
    try:
        ledger_payload, ledger_bytes = read_ledger_checkpoint_source(
            ledger_path
        )
    except AttemptLedgerError as exc:
        raise Task11ReadinessError(
            "pre-checkpoint ledger is invalid"
        ) from exc
    ledger_tip = ledger_payload["revision_chain"][-1]
    ledger_state = {
        "revision": ledger_tip["revision"],
        "revision_hash": ledger_tip["revision_hash"],
    }
    manifest = {
        "schema_version": _MANIFEST_SCHEMA,
        "repository_root": str(root),
        "plan_revision": plan_revision,
        "repair_epoch": repair_epoch,
        "candidate_head": head,
        "source_paths": list(parsed["source_paths"]),
        "test_paths": list(parsed["test_paths"]),
        "tool_paths": list(parsed["tool_paths"]),
        "plan_paths": list(parsed["plan_paths"]),
        "fixture_paths": sorted(fixture_paths),
        "deleted_paths": list(deleted),
        "deleted_base_blob_sha256_by_path": deleted_hashes,
        "mutable_evidence_paths": list(_MUTABLE_EVIDENCE_PATHS),
        "excluded_paths": list(_EXCLUDED_PATHS),
        "protected_paths": list(protected),
        "change_paths": list(changed),
        "candidate_payload_sha256": payload_sha256,
        "protected_payload_sha256": payload_sha256,
        "fixture_runtime_public_keys": [
            generated_public_key,
            retry_public_key,
        ],
        "fixture_runtime_private_key_paths": [
            str(path) for path in private_key_files
        ],
        "pre_checkpoint_ledger": {
            "path": str(ledger_path),
            "sha256": sha256(ledger_bytes).hexdigest(),
            "revision": ledger_state["revision"],
            "revision_hash": ledger_state["revision_hash"],
        },
    }
    created_private_key_files: list[Path] = []
    manifest_sha256 = sha256(_canonical_bytes(manifest)).hexdigest()
    private_keys = (
        (generated_private_key, generated_public_key),
        (retry_private_key, retry_public_key),
    )
    try:
        for index, (candidate, keypair) in enumerate(
            zip(private_key_files, private_keys, strict=True),
            start=1,
        ):
            private_key, public_key = keypair
            _write_private_json_exclusive(
                candidate,
                {
                    "schema_version": (
                        _FIXTURE_RUNTIME_PRIVATE_KEY_SCHEMA
                    ),
                    "candidate_manifest_sha256": manifest_sha256,
                    "runtime_key_slot": index,
                    "fixture_runtime_public_key": public_key,
                    "fixture_runtime_private_key": (
                        encode_runtime_private_key(private_key)
                    ),
                },
            )
            created_private_key_files.append(candidate)
    except BaseException:
        for candidate in created_private_key_files:
            candidate.unlink(missing_ok=True)
        raise
    try:
        _write_json_exclusive(
            output,
            manifest,
            label="candidate manifest",
        )
    except BaseException:
        for candidate in created_private_key_files:
            candidate.unlink(missing_ok=True)
        raise
    return manifest


def _derive_semantic_summary(
    cases_path: str | Path,
) -> dict[str, Any]:
    from app.guide.understanding.turn_meaning_contracts import (
        EXPLORE_RECOMMENDATION_BASES,
        FIT_RECOMMENDATION_BASES,
    )
    from tools.guide_gates.build_semantic_equivalence_matrix import (
        build_matrix,
    )
    from tools.guide_gates.turn_meaning_gate import load_gate_cases

    rows = build_matrix(load_gate_cases(cases_path))
    outcomes = tuple(row["expected_outcome"] for row in rows)
    recommendation_outcomes = tuple(
        outcome
        for outcome in outcomes
        if outcome["responsibility"]
        in {"recommendation", "image_recommendation"}
    )
    fit_count = sum(
        outcome["recommendation_mode"] == "fit"
        for outcome in recommendation_outcomes
    )
    explore_count = sum(
        outcome["recommendation_mode"] == "explore"
        for outcome in recommendation_outcomes
    )
    image_fit_count = sum(
        outcome["responsibility"] == "image_recommendation"
        and outcome["recommendation_mode"] == "fit"
        for outcome in recommendation_outcomes
    )
    missing_outcomes = sum(
        outcome["recommendation_mode"] is None
        or outcome["recommendation_mode_basis"] is None
        for outcome in recommendation_outcomes
    )
    cross_parent = sum(
        (
            outcome["recommendation_mode"] == "explore"
            and outcome["recommendation_mode_basis"]
            not in EXPLORE_RECOMMENDATION_BASES
        )
        or (
            outcome["recommendation_mode"] == "fit"
            and outcome["recommendation_mode_basis"]
            not in FIT_RECOMMENDATION_BASES
        )
        for outcome in recommendation_outcomes
    )
    summary = {
        "schema_version": "guide-task11-semantic-summary-v1",
        "matrix_kind": "expected_contract",
        "cases_sha256": sha256(Path(cases_path).read_bytes()).hexdigest(),
        "passed": (
            len(rows) == 128
            and fit_count > 0
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
    return summary


def build_semantic_summary(
    *,
    cases_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    summary = _derive_semantic_summary(cases_path)
    _write_json_exclusive(
        Path(output_path),
        summary,
        label="semantic summary",
    )
    return summary


def _zero_api_commands(
    manifest: dict[str, Any],
    *,
    python_executable: str,
) -> tuple[tuple[str, ...], ...]:
    test_paths = tuple(
        path
        for path in manifest["test_paths"]
        if path.endswith(".py")
    )
    return (
        ("git", "diff", "--check"),
        (
            python_executable,
            "-m",
            "compileall",
            "-q",
            "app",
            "tools",
            "tests",
        ),
        (
            "/usr/bin/sandbox-exec",
            "-p",
            ZERO_API_SANDBOX_PROFILE,
            python_executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "tools.guide_gates.zero_api_network_guard",
            *test_paths,
        ),
    )


def run_zero_api_suite(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    output_path: str | Path,
    network_report_path: str | Path,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = (
        subprocess.run
    ),
    python_executable: str = sys.executable,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    manifest, manifest_root = _validated_manifest(
        Path(manifest_path),
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if manifest_root != root:
        raise Task11ReadinessError("candidate repository root mismatch")
    commands = _zero_api_commands(
        manifest,
        python_executable=python_executable,
    )
    environment = os.environ.copy()
    for key in (
        "GUIDE_LLM_API_KEY",
        "GUIDE_COPY_LLM_API_KEY",
        "OPENAI_API_KEY",
    ):
        environment.pop(key, None)
    network_report = Path(network_report_path).resolve()
    if network_report.exists() or network_report.is_symlink():
        raise Task11ReadinessError(
            "zero API network report already exists"
        )
    environment["XIAORO_ZERO_API_NETWORK_REPORT"] = str(
        network_report
    )
    results: list[dict[str, Any]] = []
    for command in commands:
        completed = command_runner(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        results.append(
            {
                "argv": list(command),
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
        if completed.returncode != 0:
            break
    measured_network = (
        _read_object(
            network_report,
            label="zero API network report",
        )
        if network_report.is_file()
        else None
    )
    network_passed = (
        measured_network is not None
        and _network_report_passed(measured_network)
    )
    summary = {
        "schema_version": "guide-task11-zero-api-summary-v1",
        "passed": (
            len(results) == len(commands)
            and all(item["returncode"] == 0 for item in results)
            and network_passed
        ),
        "guard_active": (
            measured_network.get("guard_active")
            if measured_network is not None
            else None
        ),
        "process_guard_active": (
            measured_network.get("process_guard_active")
            if measured_network is not None
            else None
        ),
        "kernel_network_sandbox_active": (
            measured_network.get("kernel_network_sandbox_active")
            if measured_network is not None
            else None
        ),
        "child_process_policy": (
            measured_network.get("child_process_policy")
            if measured_network is not None
            else None
        ),
        "provider_call_count": (
            measured_network.get("provider_call_count")
            if measured_network is not None
            else None
        ),
        "outbound_network_attempt_count": (
            measured_network.get("outbound_network_attempt_count")
            if measured_network is not None
            else None
        ),
        "process_creation_attempt_count": (
            measured_network.get("process_creation_attempt_count")
            if measured_network is not None
            else None
        ),
        "process_creation_attempts": (
            measured_network.get("process_creation_attempts")
            if measured_network is not None
            else None
        ),
        "network_report_sha256": (
            sha256(network_report.read_bytes()).hexdigest()
            if measured_network is not None
            else None
        ),
        "candidate_manifest_sha256": expected_manifest_sha256,
        "protected_payload_sha256": (
            manifest["protected_payload_sha256"]
        ),
        "commands": results,
    }
    _write_json_exclusive(
        Path(output_path),
        summary,
        label="zero API summary",
    )
    if summary["passed"] is not True:
        raise Task11ReadinessError("zero API suite failed")
    return summary


def prepare_task11_evidence(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    semantic_summary_path: str | Path,
    zero_api_summary_path: str | Path,
    network_report_path: str | Path,
    single_path_architecture_path: str | Path,
    test_path_audit_path: str | Path,
    production_path_summary_path: str | Path,
    cases_path: str | Path,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = (
        subprocess.run
    ),
    python_executable: str = sys.executable,
) -> dict[str, dict[str, Any]]:
    root = Path(repo_root).resolve()
    for label, candidate in (
        ("semantic summary", Path(semantic_summary_path)),
        ("zero API summary", Path(zero_api_summary_path)),
        ("zero API network report", Path(network_report_path)),
    ):
        if candidate.exists() or candidate.is_symlink():
            raise Task11ReadinessError(
                f"{label} already exists: {candidate}"
            )
    manifest, manifest_root = _validated_manifest(
        Path(manifest_path),
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if manifest_root != root:
        raise Task11ReadinessError("candidate repository root mismatch")
    architecture = _read_object(
        Path(single_path_architecture_path),
        label="single-path architecture",
    )
    test_path_audit = _read_object(
        Path(test_path_audit_path),
        label="test path audit",
    )
    production_path_summary = _read_object(
        Path(production_path_summary_path),
        label="production path summary",
    )
    if not _single_path_architecture_passed(
        architecture,
        manifest=manifest,
    ):
        raise Task11ReadinessError(
            "single-path architecture failed"
        )
    if not _test_path_audit_passed(
        test_path_audit,
        manifest=manifest,
    ):
        raise Task11ReadinessError("test path audit failed")
    if not _production_path_passed(
        production_path_summary,
        candidate_manifest_sha256=expected_manifest_sha256,
        protected_payload_sha256=manifest[
            "protected_payload_sha256"
        ],
    ):
        raise Task11ReadinessError("production path summary failed")
    semantic = build_semantic_summary(
        cases_path=cases_path,
        output_path=semantic_summary_path,
    )
    zero_api = run_zero_api_suite(
        repo_root=repo_root,
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        output_path=zero_api_summary_path,
        network_report_path=network_report_path,
        command_runner=command_runner,
        python_executable=python_executable,
    )
    return {
        "single_path_architecture": architecture,
        "test_path_audit": test_path_audit,
        "production_path_summary": production_path_summary,
        "semantic_summary": semantic,
        "zero_api_summary": zero_api,
        "network_report": _read_object(
            Path(network_report_path),
            label="zero API network report",
        ),
    }


def _manifest_pre_checkpoint_ledger(
    manifest: Mapping[str, object],
    *,
    root: Path,
) -> dict[str, object]:
    mutable = manifest.get("mutable_evidence_paths")
    binding = manifest.get("pre_checkpoint_ledger")
    if (
        mutable != list(_MUTABLE_EVIDENCE_PATHS)
        or not isinstance(binding, dict)
        or set(binding)
        != {"path", "sha256", "revision", "revision_hash"}
        or binding.get("path")
        != str((root / _MUTABLE_EVIDENCE_PATHS[0]).resolve())
        or not isinstance(binding.get("sha256"), str)
        or _HEX_64_PATTERN.fullmatch(str(binding["sha256"])) is None
        or not isinstance(binding.get("revision"), int)
        or isinstance(binding.get("revision"), bool)
        or int(binding["revision"]) < 0
        or not isinstance(binding.get("revision_hash"), str)
        or _HEX_64_PATTERN.fullmatch(
            str(binding["revision_hash"])
        )
        is None
    ):
        raise Task11ReadinessError(
            "candidate pre-checkpoint ledger binding is invalid"
        )
    return dict(binding)


def _manifest_root(
    manifest_path: Path,
    manifest: dict[str, Any],
) -> Path:
    raw_root = manifest.get("repository_root")
    if not isinstance(raw_root, str) or not raw_root:
        raise Task11ReadinessError(
            "candidate repository root is invalid"
        )
    root = Path(raw_root)
    if (
        not root.is_absolute()
        or str(root.resolve()) != raw_root
        or _git_top_level(root) != root
    ):
        raise Task11ReadinessError(
            "candidate repository root is invalid"
        )
    return root


def _validated_manifest(
    path: Path,
    *,
    expected_manifest_sha256: str,
) -> tuple[dict[str, Any], Path]:
    manifest, manifest_bytes = _read_manifest_once(path)
    if manifest.get("schema_version") != _MANIFEST_SCHEMA:
        raise Task11ReadinessError("candidate manifest is invalid")
    _runtime_public_keys(manifest)
    categories = (
        "source_paths",
        "test_paths",
        "tool_paths",
        "plan_paths",
        "fixture_paths",
    )
    if any(not isinstance(manifest.get(key), list) for key in categories):
        raise Task11ReadinessError("candidate manifest is invalid")
    protected = sorted(
        path
        for key in categories
        for path in manifest[key]
    )
    if (
        len(protected) != len(set(protected))
        or manifest.get("protected_paths") != protected
    ):
        raise Task11ReadinessError(
            "candidate protected paths are invalid"
        )
    deleted = manifest.get("deleted_paths")
    if (
        not isinstance(deleted, list)
        or len(deleted) != len(set(deleted))
    ):
        raise Task11ReadinessError(
            "candidate deleted paths are invalid"
        )
    root = _manifest_root(path, manifest)
    _manifest_runtime_private_key_paths(
        manifest,
        repo_root=root,
    )
    _manifest_pre_checkpoint_ledger(
        manifest,
        root=root,
    )
    repair_epoch = manifest.get("repair_epoch")
    if (
        not isinstance(repair_epoch, int)
        or isinstance(repair_epoch, bool)
        or repair_epoch < 1
        or path.resolve().parent.name != f"repair-epoch-{repair_epoch}"
    ):
        raise Task11ReadinessError("candidate manifest repair epoch is invalid")
    if not _candidate_manifest_path_is_valid(
        path,
        root=root,
        repair_epoch=repair_epoch,
        plan_revision=manifest.get("plan_revision"),
    ):
        raise Task11ReadinessError(
            "candidate manifest canonical path is invalid"
        )
    if (
        _HEX_64_PATTERN.fullmatch(expected_manifest_sha256) is None
        or sha256(manifest_bytes).hexdigest()
        != expected_manifest_sha256
    ):
        raise Task11ReadinessError(
            "candidate manifest reviewed SHA-256 is invalid"
        )
    plan_paths = manifest.get("plan_paths")
    if (
        not isinstance(plan_paths, list)
        or not any(
            (root / str(relative)).is_file()
            and _task11_evidence_epoch(root / str(relative))
            == repair_epoch
            for relative in plan_paths
        )
    ):
        raise Task11ReadinessError(
            "candidate manifest repair epoch does not match plan"
        )
    candidate_head = manifest.get("candidate_head")
    if (
        not isinstance(candidate_head, str)
        or _HEX_40_PATTERN.fullmatch(candidate_head) is None
    ):
        raise Task11ReadinessError("candidate HEAD is invalid")
    if any((root / str(item)).exists() for item in deleted):
        raise Task11ReadinessError(
            "candidate deleted paths are invalid"
        )
    change_paths = manifest.get("change_paths")
    if (
        not isinstance(change_paths, list)
        or change_paths != sorted(set(change_paths))
        or not set(change_paths) <= {*protected, *deleted}
        or not set(deleted) <= set(change_paths)
    ):
        raise Task11ReadinessError(
            "candidate change paths are invalid"
        )
    if manifest.get("mutable_evidence_paths") != list(
        _MUTABLE_EVIDENCE_PATHS
    ):
        raise Task11ReadinessError(
            "candidate mutable evidence paths are invalid"
        )
    deleted_hashes = manifest.get(
        "deleted_base_blob_sha256_by_path"
    )
    if (
        not isinstance(deleted_hashes, dict)
        or set(deleted_hashes) != set(deleted)
    ):
        raise Task11ReadinessError(
            "candidate deleted blob hashes are invalid"
        )
    for deleted_path in deleted:
        if deleted_hashes.get(deleted_path) != sha256(
            _git_blob(
                root,
                revision=candidate_head,
                path=deleted_path,
            )
        ).hexdigest():
            raise Task11ReadinessError(
                "candidate deleted blob hash mismatch"
            )
    current = canonical_payload_sha256(root, protected)
    if (
        manifest.get("candidate_payload_sha256") != current
        or manifest.get("protected_payload_sha256") != current
    ):
        raise Task11ReadinessError("protected payload drift")
    return manifest, root


def _required_reviewed_manifest_sha256(
    readiness: Mapping[str, object],
) -> str:
    value = readiness.get("reviewed_candidate_manifest_sha256")
    if (
        not isinstance(value, str)
        or _HEX_64_PATTERN.fullmatch(value) is None
    ):
        raise Task11ReadinessError(
            "candidate manifest reviewed SHA-256 is invalid"
        )
    return value


def _require_candidate_readiness_path(
    *,
    manifest_file: Path,
    manifest: Mapping[str, object],
    readiness_path: Path,
) -> None:
    repair_epoch = manifest.get("repair_epoch")
    expected = _candidate_readiness_path(manifest_file.resolve())
    if (
        not isinstance(repair_epoch, int)
        or isinstance(repair_epoch, bool)
        or manifest_file.resolve().parent.name
        != f"repair-epoch-{repair_epoch}"
        or readiness_path.resolve() != expected
    ):
        raise Task11ReadinessError(
            "candidate readiness path is invalid"
        )


def _semantic_passed(
    payload: dict[str, Any],
    *,
    manifest: dict[str, Any],
    root: Path,
) -> bool:
    cases_path = root / _SEMANTIC_CASES_PATH
    if (
        _SEMANTIC_CASES_PATH not in manifest.get("fixture_paths", ())
        or not cases_path.is_file()
        or cases_path.is_symlink()
    ):
        return False
    try:
        expected = _derive_semantic_summary(cases_path)
    except (OSError, TypeError, ValueError):
        return False
    return payload == expected


def _zero_api_passed(
    payload: dict[str, Any],
    *,
    manifest: dict[str, Any],
    root: Path,
    network_report: dict[str, Any],
    network_report_sha256: str,
) -> bool:
    commands = payload.get("commands")
    expected = _zero_api_commands(
        manifest,
        python_executable=sys.executable,
    )
    return (
        payload.get("schema_version")
        == "guide-task11-zero-api-summary-v1"
        and payload.get("passed") is True
        and payload.get("guard_active") is True
        and payload.get("process_guard_active") is True
        and payload.get("kernel_network_sandbox_active") is True
        and payload.get("child_process_policy")
        == "kernel_inherited_network_deny"
        and payload.get("provider_call_count") == 0
        and payload.get("outbound_network_attempt_count") == 0
        and payload.get("process_creation_attempt_count") == 0
        and payload.get("process_creation_attempts") == []
        and payload.get("network_report_sha256")
        == network_report_sha256
        and _network_report_passed(network_report)
        and payload.get("protected_payload_sha256")
        == manifest["protected_payload_sha256"]
        and isinstance(commands, list)
        and len(commands) == len(expected)
        and all(
            isinstance(command, dict)
            and command.get("returncode") == 0
            and command.get("argv") == list(expected_argv)
            for command, expected_argv in zip(
                commands,
                expected,
                strict=True,
            )
        )
    )


def _network_report_passed(payload: dict[str, Any]) -> bool:
    return (
        payload.get("schema_version")
        == "guide-zero-api-network-report-v1"
        and payload.get("guard_active") is True
        and payload.get("process_guard_active") is True
        and payload.get("kernel_network_sandbox_active") is True
        and payload.get("child_process_policy")
        == "kernel_inherited_network_deny"
        and payload.get("passed") is True
        and payload.get("provider_call_count") == 0
        and payload.get("outbound_network_attempt_count") == 0
        and payload.get("attempts") == []
        and payload.get("process_creation_attempt_count") == 0
        and payload.get("process_creation_attempts") == []
    )


def _runtime_network_report_passed(
    payload: dict[str, Any],
    *,
    expected_manifest_sha256: str,
) -> bool:
    runtime_identity = payload.get("runtime_identity_sha256")
    consumed_challenge_sha256s = payload.get(
        "consumed_health_challenge_sha256s"
    )
    nonce = payload.get("measurement_nonce")
    profile = payload.get("sandbox_profile")
    runtime_profile = payload.get("runtime_sandbox_profile")
    raw_text = payload.get("seatbelt_raw_ndjson")
    if not (
        payload.get("schema_version")
        == "guide-zero-api-runtime-network-report-v2"
        and payload.get("measurement")
        == "macos-unified-log-seatbelt-kernel"
        and payload.get("guard_active") is True
        and payload.get("process_guard_active") is True
        and payload.get("kernel_network_sandbox_active") is True
        and payload.get("child_process_policy")
        == "deny_process_creation"
        and payload.get("passed") is True
        and payload.get("provider_call_count") == 0
        and payload.get("outbound_network_attempt_count") == 0
        and payload.get("attempts") == []
        and payload.get("runtime_started") is True
        and payload.get("ready_identity_written") is True
        and payload.get("shutdown_finalized") is True
        and payload.get("process_creation_attempt_count") == 0
        and payload.get("process_creation_attempts") == []
        and payload.get("process_group_quiescent") is True
        and payload.get("canary_process_groups_quiescent") is True
        and payload.get("candidate_manifest_sha256")
        == expected_manifest_sha256
        and isinstance(runtime_identity, str)
        and re.fullmatch(r"[0-9a-f]{64}", runtime_identity) is not None
        and isinstance(consumed_challenge_sha256s, list)
        and bool(consumed_challenge_sha256s)
        and len(consumed_challenge_sha256s)
        == len(set(consumed_challenge_sha256s))
        and all(
            isinstance(value, str)
            and re.fullmatch(r"[0-9a-f]{64}", value) is not None
            for value in consumed_challenge_sha256s
        )
        and isinstance(nonce, str)
        and re.fullmatch(r"[0-9a-f]{64}", nonce) is not None
        and isinstance(profile, str)
        and isinstance(runtime_profile, str)
        and isinstance(raw_text, str)
    ):
        return False
    expected_profile = (
        "(version 1)"
        "(allow default)"
        "(deny network-outbound "
        "(with telemetry) "
        f"(with message \"{nonce}\"))"
        "(allow network-outbound (remote ip \"localhost:*\"))"
        "(allow network-inbound)"
    )
    profile_digest = sha256(profile.encode("utf-8")).hexdigest()
    expected_runtime_profile = (
        expected_profile
        + "(deny process-fork "
        "(with telemetry) "
        f"(with message \"{nonce}\"))"
    )
    runtime_profile_digest = sha256(
        runtime_profile.encode("utf-8")
    ).hexdigest()
    raw = raw_text.encode("utf-8")
    if not (
        profile == expected_profile
        and payload.get("sandbox_profile_sha256") == profile_digest
        and payload.get("sandbox_identity")
        == f"macos-sandbox-exec-loopback-only:{profile_digest}"
        and runtime_profile == expected_runtime_profile
        and payload.get("runtime_sandbox_profile_sha256")
        == runtime_profile_digest
        and payload.get("runtime_sandbox_identity")
        == (
            "macos-sandbox-exec-loopback-only-no-fork:"
            f"{runtime_profile_digest}"
        )
        and payload.get("seatbelt_raw_ndjson_sha256")
        == sha256(raw).hexdigest()
        and payload.get("seatbelt_raw_byte_count") == len(raw)
        and payload.get("logger_ready") is True
        and payload.get("logger_loss_event_count") == 0
        and payload.get("logger_returncode") in {0, 130, -2}
    ):
        return False
    events: list[dict[str, object]] = []
    try:
        for line in raw_text.splitlines():
            if not line:
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                return False
            events.append(event)
    except (UnicodeError, json.JSONDecodeError):
        return False
    if (
        payload.get("seatbelt_event_count") != len(events)
        or any(event.get("eventType") == "lossEvent" for event in events)
    ):
        return False

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
    if not (
        ready
        and len(canary_begin) == 1
        and len(canary_end) == 1
        and len(begin) == len(root_child) == len(descendant) == len(end) == 1
        and len(drain_canary) == 1
        and len(drain) == 1
        and payload.get("logger_readiness_marker_count") == len(ready)
        and payload.get("logger_drain_marker_count") == len(drain)
    ):
        return False
    begin_match = begin[0][1]
    root_child_match = root_child[0][1]
    descendant_match = descendant[0][1]
    end_match = end[0][1]
    canary_begin_match = canary_begin[0][1]
    canary_end_match = canary_end[0][1]
    drain_canary_match = drain_canary[0][1]
    if (
        begin_match is None
        or root_child_match is None
        or descendant_match is None
        or end_match is None
        or canary_begin_match is None
        or canary_end_match is None
        or drain_canary_match is None
    ):
        return False
    root_pid = int(begin_match.group(1))
    canary_root_pid = int(canary_begin_match.group(1))
    root_child_pid = int(root_child_match.group(1))
    descendant_pid = int(descendant_match.group(1))
    drain_canary_pid = int(drain_canary_match.group(1))
    if not (
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
        and payload.get("descendant_canary_pid") == descendant_pid
    ):
        return False

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
        if match is None:
            if nonce in message:
                return False
            continue
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
    if (
        len(root_denials) != 1
        or len(descendant_denials) != 1
        or len(drain_denials) != 1
    ):
        return False
    root_denial_index = int(root_denials[0]["line_number"]) - 1
    descendant_denial_index = (
        int(descendant_denials[0]["line_number"]) - 1
    )
    drain_denial_index = int(drain_denials[0]["line_number"]) - 1
    if not (
        canary_begin[0][0]
        < root_denial_index
        < descendant_denial_index
        < root_child[0][0]
        < descendant[0][0]
        < canary_end[0][0]
        and drain_canary[0][0]
        < drain_denial_index
        < drain[0][0]
    ):
        return False
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
    return (
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
        == 0
    )


def _single_path_architecture_passed(
    payload: dict[str, Any],
    *,
    manifest: dict[str, Any],
) -> bool:
    modules = payload.get("inspected_modules")
    violations = payload.get("violations")
    source_paths = manifest.get("source_paths")
    if not isinstance(source_paths, list):
        return False
    expected_modules = {
        str(path)[:-3].replace("/", ".")
        for path in source_paths
        if isinstance(path, str)
        and path.startswith("app/")
        and path.endswith(".py")
        and not path.endswith("/__init__.py")
    }
    return (
        payload.get("schema_version")
        == "guide-task11-single-path-architecture-v1"
        and payload.get("passed") is True
        and isinstance(modules, list)
        and bool(modules)
        and len(modules) == len(set(modules))
        and all(isinstance(item, str) and item for item in modules)
        and payload.get("inspected_module_count") == len(modules)
        and violations == []
        and payload.get("violation_count") == 0
        and payload.get("forbidden_symbol_count", 0) == 0
        and expected_modules <= set(modules)
    )


def _test_path_audit_passed(
    payload: dict[str, Any],
    *,
    manifest: dict[str, Any],
) -> bool:
    gates = payload.get("gates")
    fixture_paths = set(manifest["fixture_paths"])
    if (
        payload.get("schema_version")
        != "guide-task11-test-path-audit-v1"
        or payload.get("passed") is not True
        or payload.get("production_path_gate_count", 0) < 1
        or payload.get("invalid_production_path_claim_count") != 0
        or payload.get("unprotected_fixture_dependency_count") != 0
        or not isinstance(gates, list)
        or not gates
    ):
        return False
    production_gates = [
        gate
        for gate in gates
        if isinstance(gate, dict)
        and gate.get("claimed_scope")
        == "production_path_from_turn_meaning"
    ]
    return (
        len(production_gates) >= 1
        and all(
            gate.get("real_entrypoint") == "/api/v1/chat/stream"
            and gate.get("layers_executed") == _RUNTIME_LAYER_ORDER
            and gate.get("layers_bypassed") == []
            and gate.get("semantic_injection_type")
            == "frozen_turn_meaning_provider"
            and gate.get("runtime_evidence_source")
            == "task11-production-path-summary"
            and gate.get("case_count") == _PRODUCTION_MATRIX_TURN_COUNT
            and gate.get("turn_count") == _PRODUCTION_MATRIX_TURN_COUNT
            and gate.get("pre_decision_rejection_count")
            == _PRE_DECISION_REJECTION_COUNT
            and gate.get("trajectory_count") == 12
            and gate.get("state_edge_count") == 40
            and _PRODUCTION_MATRIX_CASES_PATH
            in set(gate.get("fixture_files", ()))
            and set(gate.get("fixture_files", ())) <= fixture_paths
            for gate in production_gates
        )
    )


def _production_trace_passed(trace: object) -> bool:
    if not isinstance(trace, dict):
        return False
    if trace.get("partition") == "pre_decision_rejection":
        return _production_pre_decision_rejection_trace_passed(trace)
    if trace.get("partition") not in {"semantic", "state", "bounded"}:
        return False
    decision_digests = {
        trace.get("route_decision_digest"),
        trace.get("selected_processor_decision_digest"),
        trace.get("result_decision_digest"),
        trace.get("sse_decision_digest"),
    }
    selected_processor = trace.get("selected_processor")
    invocation_counts = trace.get("processor_invocation_counts")
    implementation_counts = trace.get(
        "processor_implementation_counts"
    )
    return (
        trace.get("translation_injection_count") == 1
        and trace.get("structured_understanding_injection_count") == 0
        and trace.get("compiler_call_count") == 1
        and trace.get("direct_router_bypass_count") == 0
        and trace.get("legacy_entrypoint_count") == 0
        and trace.get("router_call_count") == 1
        and len(decision_digests) == 1
        and all(
            isinstance(digest, str) and len(digest) == 64
            for digest in decision_digests
        )
        and trace.get("validated_sse_sha256")
        == trace.get("emitted_sse_sha256")
        and isinstance(trace.get("validated_sse_sha256"), str)
        and len(trace["validated_sse_sha256"]) == 64
        and isinstance(selected_processor, str)
        and bool(selected_processor)
        and isinstance(invocation_counts, dict)
        and bool(invocation_counts)
        and invocation_counts.get(selected_processor) == 1
        and all(
            isinstance(name, str)
            and bool(name)
            and type(count) is int
            and count >= 0
            and (
                count == 1
                if name == selected_processor
                else count == 0
            )
            for name, count in invocation_counts.items()
        )
        and isinstance(implementation_counts, dict)
        and bool(implementation_counts)
        and all(
            isinstance(name, str)
            and bool(name)
            and type(count) is int
            and count >= 0
            for name, count in implementation_counts.items()
        )
        and sum(implementation_counts.values()) == 1
        and trace.get(
            "selected_processor_instance_entry_count"
        )
        == 1
        and trace.get("unregistered_processor_invocation_count") == 0
        and trace.get("decision_identity_violation_count") == 0
        and trace.get("execution_result_count") == 1
        and trace.get("reducer_call_count") == 1
        and trace.get("state_save_count") == 1
        and trace.get("state_save_completed_count") == 1
        and trace.get("state_backend") == "SqliteConversationState"
        and trace.get("processor_state_write_count") == 0
        and trace.get("event_state_projection_count") == 0
        and trace.get("provider_call_count") == 0
        and trace.get("outbound_network_attempt_count") == 0
        and trace.get("accepted") is True
        and trace.get("terminal_event") == "end"
        and trace.get("committed_version")
        == trace.get("loaded_version", -2) + 1
        and trace.get("expected_state_edge")
        == trace.get("observed_state_edge")
        and trace.get("observed_layers") == _RUNTIME_LAYER_ORDER
    )


def _production_pre_decision_rejection_trace_passed(
    trace: dict[str, Any],
) -> bool:
    decision_digests = {
        trace.get("route_decision_digest"),
        trace.get("selected_processor_decision_digest"),
        trace.get("result_decision_digest"),
        trace.get("sse_decision_digest"),
    }
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
    invocation_counts = trace.get("processor_invocation_counts")
    return (
        trace.get("rejection_stage") == "pre_decision"
        and all(trace.get(field) == 0 for field in zero_count_fields)
        and decision_digests == {"0" * 64}
        and trace.get("validated_sse_sha256")
        == trace.get("emitted_sse_sha256")
        and isinstance(trace.get("validated_sse_sha256"), str)
        and len(trace["validated_sse_sha256"]) == 64
        and trace.get("selected_processor") == "none"
        and trace.get("actual_processor") == "none"
        and isinstance(invocation_counts, dict)
        and all(count == 0 for count in invocation_counts.values())
        and trace.get("processor_implementation_counts") == {}
        and trace.get("accepted") is False
        and trace.get("terminal_event") == "error"
        and trace.get("semantic_equivalence_passed") is True
        and trace.get("event_names") == ["start", "error"]
        and trace.get("coverage_edges") == []
        and trace.get("card_ids") == []
        and trace.get("committed_version")
        == trace.get("loaded_version")
        and trace.get("expected_state_edge")
        == trace.get("observed_state_edge")
        and trace.get("bounded") is False
    )


def _production_path_passed(
    payload: dict[str, Any],
    *,
    candidate_manifest_sha256: str,
    protected_payload_sha256: str,
) -> bool:
    zero_fields = (
        "actual_equivalence_failure_count",
        "bounded_failure_count",
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
        "pre_decision_rejection_failure_count",
    )
    traces = payload.get("turn_traces")
    if not isinstance(traces, list):
        return False
    semantic = [
        trace
        for trace in traces
        if isinstance(trace, dict)
        and trace.get("partition") == "semantic"
    ]
    stateful = [
        trace
        for trace in traces
        if isinstance(trace, dict)
        and trace.get("partition") in {"state", "bounded"}
    ]
    bounded = [
        trace
        for trace in traces
        if isinstance(trace, dict)
        and trace.get("partition") == "bounded"
    ]
    pre_decision_rejections = [
        trace
        for trace in traces
        if isinstance(trace, dict)
        and trace.get("partition") == "pre_decision_rejection"
    ]
    trajectories = {
        trace.get("trajectory_id")
        for trace in stateful
    }
    observed_edges = {
        edge
        for trace in stateful
        for edge in trace.get("coverage_edges", ())
        if isinstance(edge, str) and edge
    }
    required_edges = payload.get("required_state_edges")
    return (
        payload.get("schema_version")
        == "guide-task11-production-path-summary-v1"
        and payload.get("candidate_manifest_sha256")
        == candidate_manifest_sha256
        and payload.get("protected_payload_sha256")
        == protected_payload_sha256
        and isinstance(payload.get("cases_sha256"), str)
        and re.fullmatch(
            r"[0-9a-f]{64}",
            payload["cases_sha256"],
        )
        is not None
        and payload.get("passed") is True
        and payload.get("expected_contract_case_count") == 128
        and payload.get("actual_equivalence_case_count") == len(semantic)
        and len(semantic) == 128
        and payload.get("trajectory_count") == len(trajectories)
        and len(trajectories) == 12
        and payload.get("stateful_turn_count") == len(stateful)
        and len(stateful) == 48
        and payload.get("turn_count") == _PRODUCTION_MATRIX_TURN_COUNT
        and isinstance(required_edges, list)
        and len(required_edges) == 40
        and len(required_edges) == len(set(required_edges))
        and set(required_edges) <= observed_edges
        and payload.get("required_state_edge_count")
        == len(required_edges)
        and payload.get("state_edge_count") == len(required_edges)
        and payload.get("bounded_turn_count") == len(bounded)
        and len(bounded) == 9
        and payload.get("pre_decision_rejection_count")
        == len(pre_decision_rejections)
        and len(pre_decision_rejections)
        == _PRE_DECISION_REJECTION_COUNT
        and payload.get("translation_injection_count")
        == _PRODUCTION_ACCEPTED_TURN_COUNT
        and payload.get("observed_layers") == _RUNTIME_LAYER_ORDER
        and all(payload.get(field) == 0 for field in zero_fields)
        and len(traces) == _PRODUCTION_MATRIX_TURN_COUNT
        and all(_production_trace_passed(trace) for trace in traces)
    )


def _fixture_passed(
    payload: dict[str, Any],
    *,
    viewport: str,
) -> bool:
    turns = payload.get("turns")
    return (
        payload.get("schema_version")
        == "guide-mainline-contract-browser-audit-v1"
        and payload.get("trajectory_set") == "fixture"
        and payload.get("evidence_scope") == "frontend_fixture_only"
        and payload.get("backend_path_claim") is False
        and payload.get("viewport") == viewport
        and payload.get("turn_count") == len(_FIXTURE_TURN_IDS)
        and payload.get("invalid_clarification_count", 0) == 0
        and isinstance(payload.get("browser_request_count"), int)
        and not isinstance(payload.get("browser_request_count"), bool)
        and payload["browser_request_count"] >= len(_FIXTURE_TURN_IDS)
        and payload.get(
            "browser_observed_non_loopback_attempt_count"
        )
        == 0
        and payload.get("process_tree_non_loopback_attempt_count") == 0
        and isinstance(turns, list)
        and tuple(
            item.get("turn_id")
            for item in turns
            if isinstance(item, dict)
        )
        == _FIXTURE_TURN_IDS
        and payload.get("passed") is True
    )


def _read_canonical_object(path: Path, *, label: str) -> tuple[
    dict[str, Any],
    bytes,
]:
    raw = _read_regular_file_once(path, label=label)
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Task11ReadinessError(f"{label} is invalid") from exc
    if (
        not isinstance(payload, dict)
        or raw != _canonical_bytes(payload)
    ):
        raise Task11ReadinessError(f"{label} is invalid")
    return payload, raw


def _read_evidence_object_once(
    path: Path,
    *,
    label: str,
) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular_file_once(path, label=label)
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Task11ReadinessError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise Task11ReadinessError(f"{label} is invalid")
    return payload, raw


def _canonical_epoch_evidence_paths(
    manifest_path: Path,
) -> dict[str, Path]:
    epoch_root = manifest_path.absolute().parent
    suffix = _candidate_artifact_suffix(manifest_path)
    paths: dict[str, Path] = {}
    for role, relative in _EPOCH_EVIDENCE_RELATIVE_BY_ROLE.items():
        relative_path = Path(relative)
        if relative_path.parts[0] == _RUNTIME_BROWSER_EVIDENCE_DIRECTORY:
            relative_path = Path(
                f"{_RUNTIME_BROWSER_EVIDENCE_DIRECTORY}{suffix}",
                *relative_path.parts[1:],
            )
        else:
            relative_path = relative_path.with_name(
                f"{relative_path.stem}{suffix}{relative_path.suffix}"
            )
        paths[role] = epoch_root / relative_path
    return paths


def _canonical_manifest_ledger_path(
    *,
    root: Path,
    manifest: Mapping[str, object],
) -> Path:
    mutable = manifest.get("mutable_evidence_paths")
    if (
        not isinstance(mutable, list)
        or len(mutable) != 1
        or not isinstance(mutable[0], str)
    ):
        raise Task11ReadinessError(
            "candidate manifest mutable ledger path is invalid"
        )
    relative = _normalized_path(mutable[0])
    if PurePosixPath(relative).name != "smoke-attempt-ledger.json":
        raise Task11ReadinessError(
            "candidate manifest mutable ledger path is invalid"
        )
    return root / relative


def _require_manifest_ledger_checkpoint(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    manifest: Mapping[str, object],
    root: Path,
    ledger_path: Path,
    ledger: Mapping[str, object],
) -> None:
    binding = _manifest_pre_checkpoint_ledger(
        manifest,
        root=root,
    )
    chain = ledger.get("revision_chain")
    if not isinstance(chain, list):
        raise Task11ReadinessError(
            "reviewed ledger checkpoint is invalid"
        )
    matches = [
        (index, entry)
        for index, entry in enumerate(chain)
        if (
            isinstance(entry, dict)
            and entry.get("revision") == binding["revision"]
            and entry.get("revision_hash") == binding["revision_hash"]
        )
    ]
    if len(matches) != 1:
        raise Task11ReadinessError(
            "reviewed ledger checkpoint is invalid"
        )
    index, source_entry = matches[0]
    if "state_snapshot" in source_entry:
        return
    if index + 1 >= len(chain):
        raise Task11ReadinessError(
            "reviewed ledger checkpoint is missing"
        )
    checkpoint = chain[index + 1]
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("revision") != int(binding["revision"]) + 1
        or checkpoint.get("previous_hash") != binding["revision_hash"]
        or checkpoint.get("operation") != "state_checkpoint"
        or checkpoint.get("source_sha256") != binding["sha256"]
        or "state_snapshot" not in checkpoint
    ):
        raise Task11ReadinessError(
            "reviewed ledger checkpoint is invalid"
        )
    try:
        verify_ledger_checkpoint_authority(
            ledger_path=ledger_path,
            manifest_path=manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    except AttemptLedgerError as exc:
        raise Task11ReadinessError(
            "reviewed ledger checkpoint authority is invalid"
        ) from exc


def _verify_runtime_provenance(
    *,
    manifest_path: Path,
    manifest: Mapping[str, object],
    expected_manifest_sha256: str,
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
    if (
        runtime_public_key not in _runtime_public_keys(manifest)
    ):
        raise Task11ReadinessError("runtime provenance is invalid")
    _verify_runtime_signature(
        public_key=runtime_public_key,
        signature=runtime_report_signature,
        domain=_RUNTIME_REPORT_SIGNATURE_DOMAIN,
        payload=signed_runtime_report,
    )
    runtime_digest = runtime_report.get("runtime_identity_sha256")
    consumed_digests = runtime_report.get(
        "consumed_health_challenge_sha256s"
    )
    if (
        not isinstance(runtime_digest, str)
        or _HEX_64_PATTERN.fullmatch(runtime_digest) is None
        or not isinstance(consumed_digests, list)
        or len(consumed_digests) != len(browser_summaries)
        or len(consumed_digests) != len(set(consumed_digests))
        or any(
            not isinstance(value, str)
            or _HEX_64_PATTERN.fullmatch(value) is None
            for value in consumed_digests
        )
    ):
        raise Task11ReadinessError("runtime provenance is invalid")

    observed_identity_bytes: list[bytes] = []
    observed_challenge_digests: list[str] = []
    for summary_path, summary in browser_summaries:
        identity, identity_bytes = _read_canonical_object(
            summary_path.parent / _RUNTIME_IDENTITY_ARTIFACT,
            label="runtime provenance identity",
        )
        challenge, _ = _read_canonical_object(
            summary_path.parent / _CONSUMED_CHALLENGE_ARTIFACT,
            label="runtime provenance challenge",
        )
        parsed = urlsplit(str(summary.get("base_url", "")))
        try:
            summary_port = parsed.port
        except ValueError as exc:
            raise Task11ReadinessError(
                "runtime provenance is invalid"
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
        _verify_runtime_signature(
            public_key=runtime_public_key,
            signature=identity_signature,
            domain=_RUNTIME_IDENTITY_SIGNATURE_DOMAIN,
            payload=signed_identity,
        )
        identity_file_digest = sha256(identity_bytes).hexdigest()
        if (
            set(identity)
            != {
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
            or identity.get("schema_version")
            != _RUNTIME_IDENTITY_SCHEMA
            or identity.get("candidate_manifest_path")
            != str(manifest_path.resolve())
            or identity.get("candidate_manifest_sha256")
            != expected_manifest_sha256
            or identity.get("plan_revision")
            != manifest.get("plan_revision")
            or identity.get("code_revision")
            != manifest.get("candidate_head")
            or identity.get("protected_payload_sha256")
            != manifest.get("protected_payload_sha256")
            or identity.get("runtime_public_key")
            != runtime_public_key
            or not isinstance(process_identity, dict)
            or set(process_identity) != {"pid"}
            or type(process_identity.get("pid")) is not int
            or int(process_identity["pid"]) <= 0
            or parsed.scheme != "http"
            or not _is_loopback_host(parsed.hostname)
            or summary_port is None
            or identity.get("host") != parsed.hostname
            or identity.get("port") != summary_port
            or not isinstance(identity.get("state_dir"), str)
            or not identity["state_dir"]
            or not isinstance(identity.get("runtime_nonce"), str)
            or _HEX_64_PATTERN.fullmatch(identity["runtime_nonce"])
            is None
            or identity["runtime_nonce"] == "0" * 64
            or not isinstance(identity_self_digest, str)
            or identity_self_digest
            != sha256(_canonical_bytes(unsigned_identity)).hexdigest()
            or identity_file_digest != runtime_digest
            or summary.get("runtime_identity_sha256")
            != identity_file_digest
            or runtime_report.get("runtime_root_pid")
            != process_identity["pid"]
            or runtime_report.get("root_pid")
            != process_identity["pid"]
        ):
            raise Task11ReadinessError("runtime provenance is invalid")

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
        _verify_runtime_signature(
            public_key=runtime_public_key,
            signature=challenge_signature,
            domain=_RUNTIME_CHALLENGE_SIGNATURE_DOMAIN,
            payload=signed_challenge,
        )
        if (
            set(challenge)
            != {
                "schema_version",
                "runtime_identity_sha256",
                "challenge",
                "challenge_sha256",
                "challenge_signature",
            }
            or unsigned_challenge["schema_version"]
            != _RUNTIME_CHALLENGE_SCHEMA
            or unsigned_challenge["runtime_identity_sha256"]
            != identity_file_digest
            or not isinstance(unsigned_challenge["challenge"], str)
            or _HEX_64_PATTERN.fullmatch(
                unsigned_challenge["challenge"]
            )
            is None
            or unsigned_challenge["challenge"] == "0" * 64
            or not isinstance(challenge_digest, str)
            or challenge_digest
            != sha256(_canonical_bytes(unsigned_challenge)).hexdigest()
            or summary.get("consumed_health_challenge_sha256")
            != challenge_digest
        ):
            raise Task11ReadinessError("runtime provenance is invalid")
        observed_identity_bytes.append(identity_bytes)
        observed_challenge_digests.append(challenge_digest)

    if (
        len(set(observed_identity_bytes)) != 1
        or observed_challenge_digests != consumed_digests
    ):
        raise Task11ReadinessError("runtime provenance is invalid")


def _verify_fixture_artifact_index(
    summary_path: Path,
    *,
    summary: Mapping[str, object] | None = None,
) -> tuple[Path, ...]:
    if (
        not summary_path.is_file()
        or summary_path.is_symlink()
        or summary_path.name != "summary.json"
    ):
        raise Task11ReadinessError("fixture artifact index is invalid")
    summary_payload = (
        _read_evidence_object_once(
            summary_path,
            label="fixture summary",
        )[0]
        if summary is None
        else dict(summary)
    )
    turns = summary_payload.get("turns")
    index = summary_payload.get("artifact_sha256_by_path")
    if (
        not isinstance(turns, list)
        or len(turns) != len(_FIXTURE_TURN_IDS)
        or not isinstance(index, dict)
    ):
        raise Task11ReadinessError("fixture artifact index is invalid")
    expected_paths = set(_FIXTURE_ROOT_ARTIFACTS)
    for expected_turn_id, row in zip(
        _FIXTURE_TURN_IDS,
        turns,
        strict=True,
    ):
        if (
            not isinstance(row, dict)
            or row.get("turn_id") != expected_turn_id
            or row.get("directory") != expected_turn_id
        ):
            raise Task11ReadinessError(
                "fixture artifact index is invalid"
            )
        expected_paths.update(
            f"{expected_turn_id}/{name}"
            for name in _FIXTURE_TURN_ARTIFACTS
        )
    if (
        set(index) != expected_paths
        or any(
            not isinstance(relative, str)
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or PurePosixPath(relative).is_absolute()
            or ".." in PurePosixPath(relative).parts
            for relative, digest in index.items()
        )
    ):
        raise Task11ReadinessError("fixture artifact index is invalid")
    root = summary_path.parent
    actual: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path == summary_path:
            continue
        if path.is_symlink():
            raise Task11ReadinessError(
                "fixture artifact index contains a symlink"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        actual[relative] = sha256(path.read_bytes()).hexdigest()
    if actual != index:
        raise Task11ReadinessError("fixture artifact index drift")
    return tuple(root / relative for relative in sorted(index))


def _runtime_private_key_paths(
    primary_path: str | Path,
    *,
    repo_root: Path,
) -> tuple[Path, Path]:
    raw_primary = Path(primary_path).expanduser()
    if not raw_primary.is_absolute():
        raise Task11ReadinessError(
            "fixture runtime private key path must be absolute"
        )
    primary = raw_primary.parent.resolve() / raw_primary.name
    paths = (
        primary,
        retry_runtime_private_key_path(primary),
    )
    for path in paths:
        try:
            path.resolve().relative_to(repo_root)
        except ValueError:
            continue
        raise Task11ReadinessError(
            "fixture runtime private key must stay outside repository"
        )
    return paths


def _require_runtime_private_key_path_binding(
    primary_path: str | Path,
    *,
    manifest: Mapping[str, object],
    repo_root: Path,
) -> tuple[Path, Path]:
    supplied = _runtime_private_key_paths(
        primary_path,
        repo_root=repo_root,
    )
    expected = _manifest_runtime_private_key_paths(
        manifest,
        repo_root=repo_root,
    )
    if supplied != expected:
        raise Task11ReadinessError(
            "runtime private key path binding is invalid"
        )
    return expected


def _runtime_private_key_cleanup_residue_paths(
    path: Path,
) -> tuple[Path, ...]:
    prefix = f".{path.name}.destroying-"
    return tuple(
        candidate
        for candidate in path.parent.glob(f"{prefix}*")
        if candidate.name.startswith(prefix)
    )


def _require_runtime_private_keys_destroyed(
    primary_path: str | Path,
    *,
    repo_root: Path,
    manifest_sha256: str,
    runtime_public_keys: tuple[str, str],
    selected_slot: int,
) -> None:
    paths = _runtime_private_key_paths(
        primary_path,
        repo_root=repo_root,
    )
    for slot, (path, public_key) in enumerate(
        zip(paths, runtime_public_keys, strict=True),
        start=1,
    ):
        if (
            path.exists()
            or path.is_symlink()
            or bool(_runtime_private_key_cleanup_residue_paths(path))
        ):
            raise Task11ReadinessError(
                "runtime private keys were not destroyed"
            )
        if slot > selected_slot:
            _verify_runtime_private_key_destruction_receipt_file(
                path=path,
                manifest_sha256=manifest_sha256,
                expected_slot=slot,
                expected_public_key=public_key,
            )


def _runtime_private_key_destruction_receipt_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.destroyed.json")


def _read_runtime_private_key_destruction_receipt_bytes(
    *,
    path: Path,
    parent_descriptor: int,
) -> bytes | None:
    receipt = _runtime_private_key_destruction_receipt_path(path)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            receipt.name,
            (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            ),
            dir_fd=parent_descriptor,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Task11ReadinessError(
            "runtime private key cleanup receipt is invalid"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.getuid()
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o600
        ):
            raise Task11ReadinessError(
                "runtime private key cleanup receipt is invalid"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after_read = os.fstat(descriptor)
        named = os.stat(
            receipt.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise Task11ReadinessError(
            "runtime private key cleanup receipt is invalid"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if (
        not stat.S_ISREG(named.st_mode)
        or not os.path.samestat(opened, after_read)
        or not os.path.samestat(opened, named)
        or opened.st_size != after_read.st_size
        or opened.st_mtime_ns != after_read.st_mtime_ns
    ):
        raise Task11ReadinessError(
            "runtime private key cleanup receipt changed during read"
        )
    return b"".join(chunks)


def _runtime_private_key_destruction_receipt(
    *,
    path: Path,
    manifest_sha256: str,
    expected_slot: int,
    expected_public_key: str,
    key_metadata: os.stat_result,
    key_content: bytes,
    private_key: Ed25519PrivateKey,
) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "schema_version": _RUNTIME_PRIVATE_KEY_DESTRUCTION_SCHEMA,
        "candidate_manifest_sha256": manifest_sha256,
        "runtime_key_slot": expected_slot,
        "fixture_runtime_public_key": expected_public_key,
        "runtime_private_key_path": str(path),
        "key_device": key_metadata.st_dev,
        "key_inode": key_metadata.st_ino,
        "key_sha256": sha256(key_content).hexdigest(),
    }
    signature = private_key.sign(
        _RUNTIME_PRIVATE_KEY_DESTRUCTION_SIGNATURE_DOMAIN
        + _canonical_bytes(unsigned)
    )
    return {
        **unsigned,
        "signature": (
            base64.urlsafe_b64encode(signature)
            .decode("ascii")
            .rstrip("=")
        ),
    }


def _validate_runtime_private_key_destruction_receipt(
    receipt: object,
    *,
    path: Path,
    manifest_sha256: str,
    expected_slot: int,
    expected_public_key: str,
    expected_identity: tuple[int, int] | None = None,
    expected_key_sha256: str | None = None,
) -> dict[str, object]:
    required = {
        "schema_version",
        "candidate_manifest_sha256",
        "runtime_key_slot",
        "fixture_runtime_public_key",
        "runtime_private_key_path",
        "key_device",
        "key_inode",
        "key_sha256",
        "signature",
    }
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise Task11ReadinessError(
            "runtime private key cleanup receipt is invalid"
        )
    signature = receipt.get("signature")
    unsigned = {
        key: value
        for key, value in receipt.items()
        if key != "signature"
    }
    identity = (
        receipt.get("key_device"),
        receipt.get("key_inode"),
    )
    if (
        receipt.get("schema_version")
        != _RUNTIME_PRIVATE_KEY_DESTRUCTION_SCHEMA
        or receipt.get("candidate_manifest_sha256")
        != manifest_sha256
        or receipt.get("runtime_key_slot") != expected_slot
        or receipt.get("fixture_runtime_public_key")
        != expected_public_key
        or receipt.get("runtime_private_key_path") != str(path)
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in identity
        )
        or not isinstance(receipt.get("key_sha256"), str)
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(receipt.get("key_sha256")),
        )
        is None
        or (
            expected_identity is not None
            and identity != expected_identity
        )
        or (
            expected_key_sha256 is not None
            and receipt.get("key_sha256")
            != expected_key_sha256
        )
    ):
        raise Task11ReadinessError(
            "runtime private key cleanup receipt is invalid"
        )
    try:
        _verify_runtime_signature(
            public_key=expected_public_key,
            signature=signature,
            domain=_RUNTIME_PRIVATE_KEY_DESTRUCTION_SIGNATURE_DOMAIN,
            payload=unsigned,
        )
    except Task11ReadinessError as exc:
        raise Task11ReadinessError(
            "runtime private key cleanup receipt is invalid"
        ) from exc
    return dict(receipt)


def _decode_runtime_private_key_destruction_receipt(
    receipt_bytes: bytes,
    *,
    path: Path,
    manifest_sha256: str,
    expected_slot: int,
    expected_public_key: str,
    expected_identity: tuple[int, int] | None = None,
    expected_key_sha256: str | None = None,
) -> dict[str, object]:
    try:
        receipt = json.loads(receipt_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Task11ReadinessError(
            "runtime private key cleanup receipt is invalid"
        ) from exc
    if _canonical_bytes(receipt) != receipt_bytes:
        raise Task11ReadinessError(
            "runtime private key cleanup receipt is invalid"
        )
    return _validate_runtime_private_key_destruction_receipt(
        receipt,
        path=path,
        manifest_sha256=manifest_sha256,
        expected_slot=expected_slot,
        expected_public_key=expected_public_key,
        expected_identity=expected_identity,
        expected_key_sha256=expected_key_sha256,
    )


def _verify_runtime_private_key_destruction_receipt_file(
    *,
    path: Path,
    manifest_sha256: str,
    expected_slot: int,
    expected_public_key: str,
) -> dict[str, object]:
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    parent_descriptor: int | None = None
    try:
        parent_descriptor = os.open(path.parent, directory_flags)
        receipt_bytes = (
            _read_runtime_private_key_destruction_receipt_bytes(
                path=path,
                parent_descriptor=parent_descriptor,
            )
        )
        if receipt_bytes is None:
            raise Task11ReadinessError(
                "runtime private key cleanup receipt is missing"
            )
        receipt = _decode_runtime_private_key_destruction_receipt(
            receipt_bytes,
            path=path,
            manifest_sha256=manifest_sha256,
            expected_slot=expected_slot,
            expected_public_key=expected_public_key,
        )
        os.fsync(parent_descriptor)
        return receipt
    except OSError as exc:
        raise Task11ReadinessError(
            "runtime private key cleanup receipt is invalid"
        ) from exc
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _write_runtime_private_key_destruction_receipt(
    *,
    path: Path,
    parent_descriptor: int,
    payload: Mapping[str, object],
) -> None:
    receipt = _runtime_private_key_destruction_receipt_path(path)
    data = _canonical_bytes(payload)
    current = _read_runtime_private_key_destruction_receipt_bytes(
        path=path,
        parent_descriptor=parent_descriptor,
    )
    if current == data:
        return
    if current is not None:
        if len(current) >= len(data) or not data.startswith(current):
            raise Task11ReadinessError(
                "runtime private key cleanup receipt is invalid"
            )
        try:
            os.unlink(receipt.name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
        except OSError as exc:
            raise Task11ReadinessError(
                "runtime private key cleanup receipt is invalid"
            ) from exc
    descriptor: int | None = None
    try:
        descriptor = os.open(
            receipt.name,
            (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            ),
            0o600,
            dir_fd=parent_descriptor,
        )
        remaining = memoryview(data)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("runtime key cleanup receipt write failed")
            remaining = remaining[written:]
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
        named = os.stat(
            receipt.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.getuid()
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o600
            or not os.path.samestat(opened, named)
            or opened.st_size != len(data)
        ):
            raise Task11ReadinessError(
                "runtime private key cleanup receipt changed during write"
            )
        os.fsync(parent_descriptor)
    except Task11ReadinessError:
        raise
    except OSError as exc:
        raise Task11ReadinessError(
            "runtime private key cleanup receipt is invalid"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unlink_validated_runtime_private_key(
    path: Path,
    *,
    manifest_sha256: str,
    expected_slot: int,
    expected_public_key: str,
) -> None:
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    parent_descriptor: int | None = None
    parent_identity: tuple[int, int] | None = None
    file_descriptor: int | None = None
    tombstone_name: str | None = None

    def require_parent_binding() -> None:
        if parent_descriptor is None or parent_identity is None:
            raise Task11ReadinessError(
                "runtime private key cleanup parent changed"
            )
        visible_descriptor: int | None = None
        try:
            visible_descriptor = os.open(path.parent, directory_flags)
            opened_parent = os.fstat(parent_descriptor)
            visible_parent = os.fstat(visible_descriptor)
        except OSError as exc:
            raise Task11ReadinessError(
                "runtime private key cleanup parent changed"
            ) from exc
        finally:
            if visible_descriptor is not None:
                os.close(visible_descriptor)
        if (
            (opened_parent.st_dev, opened_parent.st_ino)
            != parent_identity
            or (visible_parent.st_dev, visible_parent.st_ino)
            != parent_identity
        ):
            raise Task11ReadinessError(
                "runtime private key cleanup parent changed"
            )

    try:
        parent_descriptor = os.open(path.parent, directory_flags)
        parent_metadata = os.fstat(parent_descriptor)
        parent_identity = (
            parent_metadata.st_dev,
            parent_metadata.st_ino,
        )
        tombstone_prefix = f".{path.name}.destroying-"
        tombstones = tuple(
            name
            for name in os.listdir(parent_descriptor)
            if name.startswith(tombstone_prefix)
        )
        if len(tombstones) > 1:
            raise Task11ReadinessError(
                "runtime private key cleanup target is invalid"
            )
        try:
            canonical = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            canonical = None
        receipt_bytes = (
            _read_runtime_private_key_destruction_receipt_bytes(
                path=path,
                parent_descriptor=parent_descriptor,
            )
        )
        if canonical is None and not tombstones:
            if receipt_bytes is None:
                raise Task11ReadinessError(
                    "runtime private key cleanup target is invalid"
                )
            _decode_runtime_private_key_destruction_receipt(
                receipt_bytes,
                path=path,
                manifest_sha256=manifest_sha256,
                expected_slot=expected_slot,
                expected_public_key=expected_public_key,
            )
            require_parent_binding()
            return
        if tombstones:
            tombstone_name = tombstones[0]
            match = re.fullmatch(
                re.escape(tombstone_prefix)
                + r"([0-9a-f]+)-([0-9a-f]+)",
                tombstone_name,
            )
            if match is None:
                raise Task11ReadinessError(
                    "runtime private key cleanup target is invalid"
                )
            expected_identity = (
                int(match.group(1), 16),
                int(match.group(2), 16),
            )
            file_descriptor = os.open(
                tombstone_name,
                file_flags,
                dir_fd=parent_descriptor,
            )
        else:
            if receipt_bytes is not None:
                raise Task11ReadinessError(
                    "runtime private key cleanup target is invalid"
                )
            file_descriptor = os.open(
                path.name,
                file_flags,
                dir_fd=parent_descriptor,
            )
        opened = os.fstat(file_descriptor)
        if not tombstones:
            expected_identity = (opened.st_dev, opened.st_ino)
            tombstone_name = (
                f"{tombstone_prefix}{opened.st_dev:x}-"
                f"{opened.st_ino:x}"
            )
        assert tombstone_name is not None
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        named = os.stat(
            tombstone_name if tombstones else path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        expected_links = 2 if tombstones and canonical is not None else 1
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.getuid()
            or opened.st_nlink != expected_links
            or stat.S_IMODE(opened.st_mode) != 0o600
            or not os.path.samestat(opened, named)
            or (opened.st_dev, opened.st_ino) != expected_identity
            or (
                canonical is not None
                and tombstones
                and not os.path.samestat(opened, canonical)
            )
        ):
            raise Task11ReadinessError(
                "runtime private key cleanup target is invalid"
            )
        content = b"".join(chunks)
        if not content:
            raise Task11ReadinessError(
                "runtime private key cleanup target is invalid"
            )
        if content:
            try:
                payload = json.loads(content)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise Task11ReadinessError(
                    "runtime private key cleanup target is invalid"
                ) from exc
            if (
                not isinstance(payload, dict)
                or _canonical_bytes(payload) != content
                or set(payload)
                != {
                    "schema_version",
                    "candidate_manifest_sha256",
                    "runtime_key_slot",
                    "fixture_runtime_public_key",
                    "fixture_runtime_private_key",
                }
                or payload.get("schema_version")
                != _FIXTURE_RUNTIME_PRIVATE_KEY_SCHEMA
                or payload.get("candidate_manifest_sha256")
                != manifest_sha256
                or payload.get("runtime_key_slot") != expected_slot
                or payload.get("fixture_runtime_public_key")
                != expected_public_key
            ):
                raise Task11ReadinessError(
                    "runtime private key cleanup target is invalid"
                )
            try:
                private_key = decode_runtime_private_key(
                    payload.get("fixture_runtime_private_key")
                )
            except RuntimeProofError as exc:
                raise Task11ReadinessError(
                    "runtime private key cleanup target is invalid"
                ) from exc
            if runtime_public_key(private_key) != expected_public_key:
                raise Task11ReadinessError(
                    "runtime private key cleanup target is invalid"
                )
        else:
            raise Task11ReadinessError(
                "runtime private key cleanup target is invalid"
            )
        if not tombstones:
            os.link(
                path.name,
                tombstone_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            os.fsync(parent_descriptor)
            linked = os.fstat(file_descriptor)
            tombstone = os.stat(
                tombstone_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                linked.st_nlink != 2
                or not os.path.samestat(linked, tombstone)
            ):
                raise Task11ReadinessError(
                    "runtime private key cleanup target changed"
                )
        require_parent_binding()
        if canonical is not None:
            visible_canonical = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if not os.path.samestat(opened, visible_canonical):
                raise Task11ReadinessError(
                    "runtime private key cleanup target changed"
                )
            os.unlink(path.name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
            require_parent_binding()
        tombstone = os.stat(
            tombstone_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        after_canonical_unlink = os.fstat(file_descriptor)
        if (
            after_canonical_unlink.st_nlink != 1
            or not os.path.samestat(
                after_canonical_unlink,
                tombstone,
            )
        ):
            raise Task11ReadinessError(
                "runtime private key cleanup target changed"
            )
        destruction_receipt = (
            _runtime_private_key_destruction_receipt(
                path=path,
                manifest_sha256=manifest_sha256,
                expected_slot=expected_slot,
                expected_public_key=expected_public_key,
                key_metadata=opened,
                key_content=content,
                private_key=private_key,
            )
        )
        if receipt_bytes is not None:
            existing_receipt = (
                _decode_runtime_private_key_destruction_receipt(
                    receipt_bytes,
                    path=path,
                    manifest_sha256=manifest_sha256,
                    expected_slot=expected_slot,
                    expected_public_key=expected_public_key,
                    expected_identity=(opened.st_dev, opened.st_ino),
                    expected_key_sha256=sha256(content).hexdigest(),
                )
            )
            if existing_receipt != destruction_receipt:
                raise Task11ReadinessError(
                    "runtime private key cleanup receipt is invalid"
                )
        _write_runtime_private_key_destruction_receipt(
            path=path,
            parent_descriptor=parent_descriptor,
            payload=destruction_receipt,
        )
        os.unlink(tombstone_name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
        unlinked = os.fstat(file_descriptor)
        if unlinked.st_nlink != 0:
            raise Task11ReadinessError(
                "runtime private key cleanup target changed"
            )
        os.ftruncate(file_descriptor, 0)
        os.fsync(file_descriptor)
        require_parent_binding()
    except OSError as exc:
        raise Task11ReadinessError(
            "runtime private key cleanup target is invalid"
        ) from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _destroy_unused_runtime_private_keys(
    primary_path: str | Path,
    *,
    repo_root: Path,
    manifest_sha256: str,
    runtime_public_keys: tuple[str, str],
    selected_slot: int,
) -> None:
    paths = _runtime_private_key_paths(
        primary_path,
        repo_root=repo_root,
    )
    for slot, (path, public_key) in enumerate(
        zip(paths, runtime_public_keys, strict=True),
        start=1,
    ):
        exists = path.exists() or path.is_symlink()
        cleanup_pending = bool(
            _runtime_private_key_cleanup_residue_paths(path)
        )
        if slot <= selected_slot:
            if exists or cleanup_pending:
                raise Task11ReadinessError(
                    "consumed runtime private key still exists"
                )
            continue
        _unlink_validated_runtime_private_key(
            path,
            manifest_sha256=manifest_sha256,
            expected_slot=slot,
            expected_public_key=public_key,
        )
    _require_runtime_private_keys_destroyed(
        primary_path,
        repo_root=repo_root,
        manifest_sha256=manifest_sha256,
        runtime_public_keys=runtime_public_keys,
        selected_slot=selected_slot,
    )


def _runtime_browser_bundle_paths(
    root: Path,
) -> dict[str, Path]:
    return {
        role: root / relative
        for role, relative in _RUNTIME_BROWSER_RELATIVE_BY_ROLE.items()
    }


def _validate_runtime_browser_bundle(
    *,
    bundle_root: Path,
    manifest_path: Path,
    manifest: Mapping[str, object],
    expected_manifest_sha256: str,
    expected_attempt: str,
) -> tuple[dict[str, Path], tuple[Path, ...], int]:
    paths = _runtime_browser_bundle_paths(bundle_root)
    runtime_report, _ = _read_evidence_object_once(
        paths["runtime_network_report"],
        label="runtime browser staging report",
    )
    desktop_summary, _ = _read_evidence_object_once(
        paths["desktop_summary"],
        label="runtime browser desktop summary",
    )
    mobile_summary, _ = _read_evidence_object_once(
        paths["mobile_summary"],
        label="runtime browser mobile summary",
    )
    runtime_public_keys = _runtime_public_keys(manifest)
    selected_public_key = runtime_report.get(
        "fixture_runtime_public_key"
    )
    selected_slot = (
        runtime_public_keys.index(selected_public_key) + 1
        if selected_public_key in runtime_public_keys
        else 0
    )
    if (
        selected_slot == 0
        or expected_attempt
        != _RUNTIME_BROWSER_ATTEMPTS[selected_slot - 1]
        or not _runtime_network_report_passed(
            runtime_report,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        or not _fixture_passed(
            desktop_summary,
            viewport="desktop",
        )
        or not _fixture_passed(
            mobile_summary,
            viewport="mobile",
        )
    ):
        raise Task11ReadinessError(
            "runtime browser staging is invalid"
        )
    desktop_artifacts = _verify_fixture_artifact_index(
        paths["desktop_summary"],
        summary=desktop_summary,
    )
    mobile_artifacts = _verify_fixture_artifact_index(
        paths["mobile_summary"],
        summary=mobile_summary,
    )
    _verify_runtime_provenance(
        manifest_path=manifest_path,
        manifest=manifest,
        expected_manifest_sha256=expected_manifest_sha256,
        runtime_report=runtime_report,
        browser_summaries=(
            (paths["desktop_summary"], desktop_summary),
            (paths["mobile_summary"], mobile_summary),
        ),
    )
    expected_files = {
        paths["runtime_network_report"],
        paths["desktop_summary"],
        paths["mobile_summary"],
        *desktop_artifacts,
        *mobile_artifacts,
    }
    actual_files: set[Path] = set()
    actual_directories: set[Path] = set()
    for path in bundle_root.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise Task11ReadinessError(
                "runtime browser staging is invalid"
            )
        if stat.S_ISREG(metadata.st_mode):
            actual_files.add(path)
        elif stat.S_ISDIR(metadata.st_mode):
            actual_directories.add(path)
        else:
            raise Task11ReadinessError(
                "runtime browser staging is invalid"
            )
    expected_directories = {
        parent
        for path in expected_files
        for parent in path.parents
        if parent != bundle_root and bundle_root in parent.parents
    }
    if (
        actual_files != expected_files
        or actual_directories != expected_directories
    ):
        raise Task11ReadinessError(
            "runtime browser staging is invalid"
        )
    return paths, tuple(sorted(expected_files)), selected_slot


def _write_runtime_browser_bundle_snapshot(
    *,
    destination: Path,
    relative_bytes: Mapping[str, bytes],
) -> None:
    for relative, payload in sorted(relative_bytes.items()):
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(
            output,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("runtime browser staging write failed")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    directories = sorted(
        (
            path
            for path in destination.rglob("*")
            if path.is_dir()
        ),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    directories.append(destination)
    for directory in directories:
        descriptor = os.open(
            directory,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _rename_runtime_browser_bundle_no_replace(
    source: Path,
    destination: Path,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        try:
            rename = libc.renamex_np
        except AttributeError as exc:
            raise Task11ReadinessError(
                "runtime browser promotion is unsupported"
            ) from exc
        rename.argtypes = (
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(
            os.fsencode(source),
            os.fsencode(destination),
            _RENAME_EXCL,
        )
    elif sys.platform.startswith("linux"):
        try:
            rename = libc.renameat2
        except AttributeError as exc:
            raise Task11ReadinessError(
                "runtime browser promotion is unsupported"
            ) from exc
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(
            _AT_FDCWD,
            os.fsencode(source),
            _AT_FDCWD,
            os.fsencode(destination),
            _RENAME_NOREPLACE,
        )
    else:
        raise Task11ReadinessError(
            "runtime browser promotion is unsupported"
        )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise Task11ReadinessError(
            "runtime browser canonical evidence already exists"
        )
    raise OSError(
        error_number,
        os.strerror(error_number),
        str(destination),
    )


def promote_runtime_browser_evidence(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    attempt_root: str | Path,
    fixture_runtime_private_key_path: str | Path,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    manifest_file = Path(manifest_path)
    manifest, validated_root = _validated_manifest(
        manifest_file,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if validated_root != root:
        raise Task11ReadinessError(
            "runtime browser repository root is invalid"
        )
    _require_runtime_private_key_path_binding(
        fixture_runtime_private_key_path,
        manifest=manifest,
        repo_root=root,
    )
    raw_attempt = Path(attempt_root).expanduser()
    if not raw_attempt.is_absolute() or raw_attempt.name not in (
        _RUNTIME_BROWSER_ATTEMPTS
    ):
        raise Task11ReadinessError(
            "runtime browser staging is invalid"
        )
    staging = raw_attempt.resolve()
    try:
        staging.relative_to(root)
    except ValueError:
        pass
    else:
        raise Task11ReadinessError(
            "runtime browser staging must stay outside repository"
        )
    if (
        not staging.is_dir()
        or staging.is_symlink()
        or staging.name != raw_attempt.name
    ):
        raise Task11ReadinessError(
            "runtime browser staging is invalid"
        )
    try:
        _, staged_files, selected_slot = (
            _validate_runtime_browser_bundle(
                bundle_root=staging,
                manifest_path=manifest_file,
                manifest=manifest,
                expected_manifest_sha256=(
                    expected_manifest_sha256
                ),
                expected_attempt=staging.name,
            )
        )
        relative_bytes = {
            path.relative_to(staging).as_posix(): (
                _read_regular_file_once(
                    path,
                    label="runtime browser staging artifact",
                )
            )
            for path in staged_files
        }
    except Task11ReadinessError as exc:
        raise Task11ReadinessError(
            "runtime browser staging is invalid"
        ) from exc

    canonical_name = (
        f"{_RUNTIME_BROWSER_EVIDENCE_DIRECTORY}"
        f"{_candidate_artifact_suffix(manifest_file)}"
    )
    canonical = manifest_file.absolute().parent / canonical_name
    if canonical.exists() or canonical.is_symlink():
        try:
            _, canonical_files, canonical_slot = (
                _validate_runtime_browser_bundle(
                    bundle_root=canonical,
                    manifest_path=manifest_file,
                    manifest=manifest,
                    expected_manifest_sha256=(
                        expected_manifest_sha256
                    ),
                    expected_attempt=staging.name,
                )
            )
            canonical_bytes = {
                path.relative_to(canonical).as_posix(): (
                    _read_regular_file_once(
                        path,
                        label="runtime browser canonical artifact",
                    )
                )
                for path in canonical_files
            }
        except Task11ReadinessError as exc:
            raise Task11ReadinessError(
                "runtime browser canonical evidence already exists"
            ) from exc
        if (
            canonical_slot != selected_slot
            or canonical_bytes != relative_bytes
        ):
            raise Task11ReadinessError(
                "runtime browser canonical evidence already exists"
            )
    else:
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{canonical_name}.",
                suffix=".staging",
                dir=canonical.parent,
            )
        )
        promoted = False
        try:
            os.chmod(temporary, 0o700)
            _write_runtime_browser_bundle_snapshot(
                destination=temporary,
                relative_bytes=relative_bytes,
            )
            _, copied_files, copied_slot = (
                _validate_runtime_browser_bundle(
                    bundle_root=temporary,
                    manifest_path=manifest_file,
                    manifest=manifest,
                    expected_manifest_sha256=(
                        expected_manifest_sha256
                    ),
                    expected_attempt=staging.name,
                )
            )
            copied_bytes = {
                path.relative_to(temporary).as_posix(): (
                    _read_regular_file_once(
                        path,
                        label="runtime browser copied artifact",
                    )
                )
                for path in copied_files
            }
            if (
                copied_slot != selected_slot
                or copied_bytes != relative_bytes
            ):
                raise Task11ReadinessError(
                    "runtime browser staging copy changed"
                )
            _rename_runtime_browser_bundle_no_replace(
                temporary,
                canonical,
            )
            promoted = True
            parent_descriptor = os.open(
                canonical.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
            )
            try:
                os.fsync(parent_descriptor)
            finally:
                os.close(parent_descriptor)
        finally:
            if not promoted:
                shutil.rmtree(temporary, ignore_errors=True)
    _destroy_unused_runtime_private_keys(
        fixture_runtime_private_key_path,
        repo_root=root,
        manifest_sha256=expected_manifest_sha256,
        runtime_public_keys=_runtime_public_keys(manifest),
        selected_slot=selected_slot,
    )
    return {
        "schema_version": "guide-task11-runtime-browser-promotion-v1",
        "passed": True,
        "attempt_id": staging.name,
        "runtime_key_slot": selected_slot,
        "fixture_runtime_public_key": _runtime_public_keys(manifest)[
            selected_slot - 1
        ],
        "candidate_manifest_sha256": expected_manifest_sha256,
        "canonical_bundle": str(canonical.resolve()),
        "artifact_sha256_by_path": {
            relative: sha256(payload).hexdigest()
            for relative, payload in sorted(relative_bytes.items())
        },
    }


def _readiness_fixture_artifact_paths(
    *,
    root: Path,
    readiness: Mapping[str, object],
) -> tuple[str, ...]:
    evidence_files = readiness.get("evidence_files")
    if not isinstance(evidence_files, dict):
        raise Task11ReadinessError(
            "readiness evidence binding is invalid"
        )
    paths: list[str] = []
    for role in ("desktop_summary", "mobile_summary"):
        raw_path = evidence_files.get(role)
        if not isinstance(raw_path, str):
            raise Task11ReadinessError(
                "readiness evidence binding is invalid"
            )
        paths.extend(
            _repository_relative(root, path)
            for path in _verify_fixture_artifact_index(Path(raw_path))
        )
    expected_count = 2 * (
        len(_FIXTURE_ROOT_ARTIFACTS)
        + len(_FIXTURE_TURN_IDS) * len(_FIXTURE_TURN_ARTIFACTS)
    )
    if len(paths) != expected_count or len(set(paths)) != expected_count:
        raise Task11ReadinessError(
            "fixture artifact path binding is invalid"
        )
    return tuple(sorted(paths))


def _current_circuit_state(
    ledger: dict[str, Any],
    *,
    plan_revision: str,
) -> str:
    failures: dict[str, int] = {}
    for attempt in ledger["attempts"]:
        if (
            not isinstance(attempt, dict)
            or attempt.get("plan_revision") != plan_revision
        ):
            continue
        if attempt.get("result") == "unverifiable_history":
            return "open"
        if attempt.get("result") != "failed":
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
            failures[owner] = failures.get(owner, 0) + 1
    return (
        "open"
        if any(count >= 2 for count in failures.values())
        else "closed"
    )


def derive_candidate_readiness(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    semantic_summary_path: str | Path,
    zero_api_summary_path: str | Path,
    network_report_path: str | Path,
    runtime_network_report_path: str | Path,
    single_path_architecture_path: str | Path,
    test_path_audit_path: str | Path,
    production_path_summary_path: str | Path,
    independent_audit_path: str | Path,
    desktop_summary_path: str | Path,
    mobile_summary_path: str | Path,
    ledger_path: str | Path,
    output_path: str | Path | None = None,
    _ledger_snapshot: Mapping[str, Any] | None = None,
    _evidence_reads: Mapping[
        str,
        tuple[dict[str, Any], bytes],
    ]
    | None = None,
) -> dict[str, Any]:
    if output_path is not None:
        raise Task11ReadinessError(
            "seal_candidate_readiness is the only readiness writer"
        )
    manifest_file = Path(manifest_path)
    manifest, root = _validated_manifest(
        manifest_file,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    evidence_paths = {
        "semantic_summary": Path(semantic_summary_path),
        "zero_api_summary": Path(zero_api_summary_path),
        "network_report": Path(network_report_path),
        "runtime_network_report": Path(
            runtime_network_report_path
        ),
        "single_path_architecture": Path(
            single_path_architecture_path
        ),
        "test_path_audit": Path(test_path_audit_path),
        "production_path_summary": Path(
            production_path_summary_path
        ),
        "independent_audit": Path(independent_audit_path),
        "desktop_summary": Path(desktop_summary_path),
        "mobile_summary": Path(mobile_summary_path),
    }
    canonical_evidence_paths = _canonical_epoch_evidence_paths(
        manifest_file
    )
    if (
        set(evidence_paths) != set(canonical_evidence_paths)
        or any(
            path.absolute() != canonical_evidence_paths[role]
            for role, path in evidence_paths.items()
        )
    ):
        raise Task11ReadinessError(
            "readiness canonical epoch evidence path is invalid"
        )
    canonical_ledger_path = _canonical_manifest_ledger_path(
        root=root,
        manifest=manifest,
    )
    if Path(ledger_path).absolute() != canonical_ledger_path:
        raise Task11ReadinessError(
            "readiness canonical ledger path is invalid"
        )
    evidence_reads = (
        {
            role: _read_evidence_object_once(
                path,
                label=role.replace("_", " "),
            )
            for role, path in evidence_paths.items()
        }
        if _evidence_reads is None
        else dict(_evidence_reads)
    )
    if set(evidence_reads) != set(evidence_paths):
        raise Task11ReadinessError(
            "readiness evidence binding is invalid"
        )
    evidence = {
        role: payload
        for role, (payload, _) in evidence_reads.items()
    }
    evidence_bytes = {
        role: raw
        for role, (_, raw) in evidence_reads.items()
    }
    manifest_sha256 = expected_manifest_sha256
    semantic_passed = _semantic_passed(
        evidence["semantic_summary"],
        manifest=manifest,
        root=root,
    )
    if not semantic_passed:
        raise Task11ReadinessError(
            "semantic matrix evidence failed"
        )
    network_report_passed = _network_report_passed(
        evidence["network_report"]
    )
    if not network_report_passed:
        raise Task11ReadinessError(
            "zero API network evidence failed"
        )
    runtime_network_report_passed = _runtime_network_report_passed(
        evidence["runtime_network_report"],
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if not runtime_network_report_passed:
        raise Task11ReadinessError(
            "zero API runtime network evidence failed"
        )
    single_path_architecture_passed = (
        _single_path_architecture_passed(
            evidence["single_path_architecture"],
            manifest=manifest,
        )
    )
    if not single_path_architecture_passed:
        raise Task11ReadinessError(
            "single-path architecture failed"
        )
    zero_api_passed = (
        evidence["zero_api_summary"].get(
            "candidate_manifest_sha256"
        )
        == manifest_sha256
        and _zero_api_passed(
            evidence["zero_api_summary"],
            manifest=manifest,
            root=root,
            network_report=evidence["network_report"],
            network_report_sha256=sha256(
                evidence_bytes["network_report"]
            ).hexdigest(),
        )
    )
    if not zero_api_passed:
        raise Task11ReadinessError("zero API evidence failed")
    test_path_audit_passed = _test_path_audit_passed(
        evidence["test_path_audit"],
        manifest=manifest,
    )
    if not test_path_audit_passed:
        raise Task11ReadinessError("test path audit failed")
    production_path_passed = _production_path_passed(
        evidence["production_path_summary"],
        candidate_manifest_sha256=manifest_sha256,
        protected_payload_sha256=manifest[
            "protected_payload_sha256"
        ],
    )
    if not production_path_passed:
        raise Task11ReadinessError(
            "production path summary failed"
        )
    production_cases_path = root / _PRODUCTION_MATRIX_CASES_PATH
    if (
        _PRODUCTION_MATRIX_CASES_PATH
        not in set(manifest.get("fixture_paths", ()))
        or not production_cases_path.is_file()
        or production_cases_path.is_symlink()
        or evidence["production_path_summary"].get("cases_sha256")
        != sha256(production_cases_path.read_bytes()).hexdigest()
    ):
        raise Task11ReadinessError(
            "production path summary failed"
        )
    _validate_bounded_trajectory_messages(
        repo_root=root,
        cases_path=production_cases_path,
    )
    _verify_fixture_artifact_index(
        evidence_paths["desktop_summary"],
        summary=evidence["desktop_summary"],
    )
    desktop_fixture_passed = _fixture_passed(
        evidence["desktop_summary"],
        viewport="desktop",
    )
    if not desktop_fixture_passed:
        raise Task11ReadinessError("desktop fixture evidence failed")
    _verify_fixture_artifact_index(
        evidence_paths["mobile_summary"],
        summary=evidence["mobile_summary"],
    )
    mobile_fixture_passed = _fixture_passed(
        evidence["mobile_summary"],
        viewport="mobile",
    )
    if not mobile_fixture_passed:
        raise Task11ReadinessError("mobile fixture evidence failed")
    _verify_runtime_provenance(
        manifest_path=manifest_file,
        manifest=manifest,
        expected_manifest_sha256=expected_manifest_sha256,
        runtime_report=evidence["runtime_network_report"],
        browser_summaries=(
            (
                evidence_paths["desktop_summary"],
                evidence["desktop_summary"],
            ),
            (
                evidence_paths["mobile_summary"],
                evidence["mobile_summary"],
            ),
        ),
    )
    audit = evidence["independent_audit"]
    reviewed_evidence_sha256 = audit.get(
        "reviewed_evidence_sha256"
    )
    expected_reviewed_evidence_sha256 = {
        "candidate_manifest": manifest_sha256,
        **{
            role: sha256(evidence_bytes[role]).hexdigest()
            for role in evidence_paths
            if role != "independent_audit"
        },
    }
    independent_audit_passed = (
        audit.get("schema_version")
        == "guide-task11-independent-audit-v1"
        and audit.get("passed") is True
        and audit.get("plan_revision") == manifest["plan_revision"]
        and audit.get("repair_epoch") == manifest["repair_epoch"]
        and audit.get("candidate_manifest_sha256") == manifest_sha256
        and audit.get("protected_payload_sha256")
        == manifest["protected_payload_sha256"]
        and audit.get("production_diff_sha256")
        == _candidate_diff_sha256(
            root,
            revision=manifest["candidate_head"],
            change_paths=manifest["change_paths"],
        )
        and audit.get("finding_count") == 0
        and audit.get("p0_finding_count") == 0
        and audit.get("p1_finding_count") == 0
        and audit.get("findings") == []
        and isinstance(audit.get("checks"), dict)
        and set(audit["checks"]) == _INDEPENDENT_AUDIT_CHECKS
        and all(value is True for value in audit["checks"].values())
        and reviewed_evidence_sha256
        == expected_reviewed_evidence_sha256
        and _task12_execution_audit_passed(
            audit=audit,
            manifest=manifest,
            root=root,
        )
    )
    if not independent_audit_passed:
        raise Task11ReadinessError(
            "independent audit evidence failed"
        )
    ledger = (
        read_ledger(ledger_path)
        if _ledger_snapshot is None
        else dict(_ledger_snapshot)
    )
    _require_manifest_ledger_checkpoint(
        manifest_path=manifest_file,
        expected_manifest_sha256=expected_manifest_sha256,
        manifest=manifest,
        root=root,
        ledger_path=Path(ledger_path),
        ledger=ledger,
    )
    anchor = ledger_anchor(ledger)
    circuit_state = _current_circuit_state(
        ledger,
        plan_revision=manifest["plan_revision"],
    )
    invalid_clarifications = sum(
        int(evidence[key].get("invalid_clarification_count", 0))
        for key in ("desktop_summary", "mobile_summary")
    )
    clarification_evidence_passed = invalid_clarifications == 0
    circuit_closed = circuit_state == "closed"
    affected_zero_api_passed = (
        zero_api_passed
        and network_report_passed
        and runtime_network_report_passed
    )
    production_path_matrix_passed = (
        test_path_audit_passed
        and production_path_passed
    )
    step_0_passed = semantic_passed and affected_zero_api_passed
    step_0_5_passed = (
        semantic_passed and single_path_architecture_passed
    )
    step_4_5_passed = (
        semantic_passed
        and affected_zero_api_passed
        and desktop_fixture_passed
        and mobile_fixture_passed
        and independent_audit_passed
        and clarification_evidence_passed
        and circuit_closed
    )
    step_4_6_passed = (
        single_path_architecture_passed
        and production_path_matrix_passed
        and runtime_network_report_passed
        and independent_audit_passed
        and circuit_closed
    )
    readiness = {
        "schema_version": _READINESS_SCHEMA,
        "plan_revision": manifest["plan_revision"],
        "reviewed_candidate_manifest_sha256": (
            expected_manifest_sha256
        ),
        "candidate_head": manifest["candidate_head"],
        "candidate_payload_sha256": (
            manifest["candidate_payload_sha256"]
        ),
        "protected_payload_sha256": (
            manifest["protected_payload_sha256"]
        ),
        "step_0_passed": step_0_passed,
        "step_0_5_passed": step_0_5_passed,
        "step_4_5_passed": step_4_5_passed,
        "step_4_6_passed": step_4_6_passed,
        "affected_zero_api_passed": affected_zero_api_passed,
        "single_path_architecture_passed": (
            single_path_architecture_passed
        ),
        "production_path_matrix_passed": (
            production_path_matrix_passed
        ),
        "desktop_fixture_passed": desktop_fixture_passed,
        "mobile_fixture_passed": mobile_fixture_passed,
        "invalid_clarification_count": invalid_clarifications,
        "provider_call_count": (
            evidence["network_report"]["provider_call_count"]
        ),
        "outbound_network_attempt_count": (
            evidence["network_report"][
                "outbound_network_attempt_count"
            ]
        ),
        "runtime_outbound_network_attempt_count": (
            evidence["runtime_network_report"][
                "outbound_network_attempt_count"
            ]
        ),
        "runtime_process_tree_non_loopback_attempt_count": (
            evidence["runtime_network_report"][
                "runtime_process_tree_non_loopback_attempt_count"
            ]
        ),
        "fixture_browser_non_loopback_attempt_count": sum(
            int(
                evidence[key][
                    "browser_observed_non_loopback_attempt_count"
                ]
            )
            for key in ("desktop_summary", "mobile_summary")
        ),
        "fixture_process_tree_non_loopback_attempt_count": sum(
            int(
                evidence[key][
                    "process_tree_non_loopback_attempt_count"
                ]
            )
            for key in ("desktop_summary", "mobile_summary")
        ),
        "ledger_anchor_revision": anchor["revision"],
        "ledger_anchor_hash": anchor["revision_hash"],
        "ledger_path": str(canonical_ledger_path),
        "circuit_state": circuit_state,
        "evidence_files": {
            "candidate_manifest": str(manifest_file.resolve()),
            **{
                role: str(path.resolve())
                for role, path in evidence_paths.items()
            },
        },
        "evidence_sha256": {
            "candidate_manifest": expected_manifest_sha256,
            **{
                role: sha256(evidence_bytes[role]).hexdigest()
                for role in evidence_paths
            },
        },
    }
    if not clarification_evidence_passed or not circuit_closed:
        raise Task11ReadinessError("Task 11 readiness is blocked")
    return readiness


def seal_candidate_readiness(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    semantic_summary_path: str | Path,
    zero_api_summary_path: str | Path,
    network_report_path: str | Path,
    runtime_network_report_path: str | Path,
    single_path_architecture_path: str | Path,
    test_path_audit_path: str | Path,
    production_path_summary_path: str | Path,
    independent_audit_path: str | Path,
    desktop_summary_path: str | Path,
    mobile_summary_path: str | Path,
    ledger_path: str | Path,
    output_path: str | Path,
    fixture_runtime_private_key_path: str | Path,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    manifest, root = _validated_manifest(
        manifest_file,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    runtime_public_keys = _runtime_public_keys(manifest)
    runtime_report, _ = _read_evidence_object_once(
        Path(runtime_network_report_path),
        label="runtime network report",
    )
    selected_public_key = runtime_report.get(
        "fixture_runtime_public_key"
    )
    if selected_public_key not in runtime_public_keys:
        raise Task11ReadinessError("runtime provenance is invalid")
    selected_slot = (
        runtime_public_keys.index(str(selected_public_key)) + 1
    )
    _require_candidate_readiness_path(
        manifest_file=manifest_file,
        manifest=manifest,
        readiness_path=Path(output_path),
    )
    output_file = _candidate_readiness_path(
        manifest_file.resolve()
    )
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        parent_descriptor = os.open(output_file.parent, directory_flags)
    except OSError as exc:
        raise Task11ReadinessError(
            "candidate readiness parent changed"
        ) from exc
    try:
        parent_metadata = os.fstat(parent_descriptor)
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != os.getuid()
        ):
            raise Task11ReadinessError(
                "candidate readiness parent changed"
            )
        parent_identity = (
            parent_metadata.st_dev,
            parent_metadata.st_ino,
        )
        _require_readiness_parent_binding(
            parent_path=output_file.parent,
            parent_descriptor=parent_descriptor,
            parent_identity=parent_identity,
            manifest_name=manifest_file.name,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        _require_runtime_private_key_path_binding(
            fixture_runtime_private_key_path,
            manifest=manifest,
            repo_root=root,
        )
        try:
            _require_runtime_private_keys_destroyed(
                fixture_runtime_private_key_path,
                repo_root=root,
                manifest_sha256=expected_manifest_sha256,
                runtime_public_keys=runtime_public_keys,
                selected_slot=selected_slot,
            )
        except Task11ReadinessError:
            _rollback_recoverable_readiness_link(
                path=output_file,
                parent_descriptor=parent_descriptor,
            )
            raise
        readiness = derive_candidate_readiness(
            manifest_path=manifest_file,
            expected_manifest_sha256=expected_manifest_sha256,
            semantic_summary_path=semantic_summary_path,
            zero_api_summary_path=zero_api_summary_path,
            network_report_path=network_report_path,
            runtime_network_report_path=runtime_network_report_path,
            single_path_architecture_path=single_path_architecture_path,
            test_path_audit_path=test_path_audit_path,
            production_path_summary_path=production_path_summary_path,
            independent_audit_path=independent_audit_path,
            desktop_summary_path=desktop_summary_path,
            mobile_summary_path=mobile_summary_path,
            ledger_path=ledger_path,
        )
        if canonical_payload_sha256(
            root,
            tuple(str(path) for path in manifest["protected_paths"]),
        ) != manifest["protected_payload_sha256"]:
            raise Task11ReadinessError("protected payload drift")
        _require_runtime_private_keys_destroyed(
            fixture_runtime_private_key_path,
            repo_root=root,
            manifest_sha256=expected_manifest_sha256,
            runtime_public_keys=runtime_public_keys,
            selected_slot=selected_slot,
        )
        _write_readiness_exclusive(
            output_file,
            readiness,
            manifest_path=manifest_file,
            expected_manifest_sha256=expected_manifest_sha256,
            parent_descriptor=parent_descriptor,
            parent_identity=parent_identity,
            repo_root=root,
            protected_paths=tuple(
                str(path) for path in manifest["protected_paths"]
            ),
            protected_payload_sha256=str(
                manifest["protected_payload_sha256"]
            ),
            fixture_runtime_private_key_path=Path(
                fixture_runtime_private_key_path
            ),
            runtime_public_keys=runtime_public_keys,
            selected_slot=selected_slot,
        )
        return readiness
    finally:
        os.close(parent_descriptor)


def verify_saved_readiness(
    *,
    readiness_path: str | Path,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    semantic_summary_path: str | Path,
    zero_api_summary_path: str | Path,
    network_report_path: str | Path,
    runtime_network_report_path: str | Path,
    single_path_architecture_path: str | Path,
    test_path_audit_path: str | Path,
    production_path_summary_path: str | Path,
    independent_audit_path: str | Path,
    desktop_summary_path: str | Path,
    mobile_summary_path: str | Path,
    ledger_path: str | Path,
    _evidence_reads: Mapping[
        str,
        tuple[dict[str, Any], bytes],
    ]
    | None = None,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    manifest, _ = _validated_manifest(
        manifest_file,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    _require_candidate_readiness_path(
        manifest_file=manifest_file,
        manifest=manifest,
        readiness_path=Path(readiness_path),
    )
    saved = _read_object(Path(readiness_path), label="readiness")
    ledger_snapshot = read_ledger(ledger_path)
    derived = derive_candidate_readiness(
        manifest_path=manifest_file,
        expected_manifest_sha256=expected_manifest_sha256,
        semantic_summary_path=semantic_summary_path,
        zero_api_summary_path=zero_api_summary_path,
        network_report_path=network_report_path,
        runtime_network_report_path=runtime_network_report_path,
        single_path_architecture_path=(
            single_path_architecture_path
        ),
        test_path_audit_path=test_path_audit_path,
        production_path_summary_path=production_path_summary_path,
        independent_audit_path=independent_audit_path,
        desktop_summary_path=desktop_summary_path,
        mobile_summary_path=mobile_summary_path,
        ledger_path=ledger_path,
        _ledger_snapshot=ledger_snapshot,
        _evidence_reads=_evidence_reads,
    )
    try:
        verify_ledger_extension(
            ledger_snapshot,
            anchor_revision=saved.get("ledger_anchor_revision"),
            anchor_hash=saved.get("ledger_anchor_hash"),
        )
    except ValueError as exc:
        raise Task11ReadinessError(
            "saved readiness ledger anchor is invalid"
        ) from exc
    derived["ledger_anchor_revision"] = saved.get(
        "ledger_anchor_revision"
    )
    derived["ledger_anchor_hash"] = saved.get("ledger_anchor_hash")
    if saved != derived:
        raise Task11ReadinessError("saved readiness does not match evidence")
    return derived


def _task12_execution_audit_passed(
    *,
    audit: Mapping[str, object],
    manifest: Mapping[str, object],
    root: Path,
) -> bool:
    checks = audit.get("checks")
    hashes = audit.get("task12_execution_tool_sha256")
    protected = manifest.get("protected_paths")
    if (
        not isinstance(checks, dict)
        or checks.get("task12_execution_tools") is not True
        or not isinstance(hashes, dict)
        or set(hashes) != set(_TASK12_EXECUTION_PATHS)
        or not isinstance(protected, list)
        or not set(_TASK12_EXECUTION_PATHS) <= set(protected)
    ):
        return False
    return all(
        (root / relative).is_file()
        and not (root / relative).is_symlink()
        and hashes.get(relative)
        == sha256((root / relative).read_bytes()).hexdigest()
        for relative in _TASK12_EXECUTION_PATHS
    )


def verify_task11_readiness(
    *,
    readiness_path: str | Path,
    ledger_path: str | Path,
    expected_manifest_sha256: str,
    fixture_bundle_verifier: Callable[[Path], None] | None = None,
    expected_candidate_head: str | None = None,
) -> dict[str, Any]:
    saved = _read_object(Path(readiness_path), label="readiness")
    if saved.get("schema_version") == _RELEASE_READINESS_SCHEMA:
        return verify_release_readiness(
            readiness_path=readiness_path,
            require_head=str(saved.get("task11_commit")),
            expected_manifest_sha256=expected_manifest_sha256,
            ledger_path=ledger_path,
        )
    files = saved.get("evidence_files")
    hashes = saved.get("evidence_sha256")
    required = {
        "candidate_manifest",
        "semantic_summary",
        "zero_api_summary",
        "network_report",
        "runtime_network_report",
        "single_path_architecture",
        "test_path_audit",
        "production_path_summary",
        "independent_audit",
        "desktop_summary",
        "mobile_summary",
    }
    if (
        not isinstance(files, dict)
        or not isinstance(hashes, dict)
        or set(files) != required
        or set(hashes) != required
    ):
        raise Task11ReadinessError(
            "readiness evidence binding is invalid"
        )
    evidence_reads: dict[
        str,
        tuple[dict[str, Any], bytes],
    ] = {}
    for role in required:
        path = Path(str(files[role]))
        payload, raw = _read_evidence_object_once(
            path,
            label=f"readiness evidence {role}",
        )
        evidence_reads[role] = (payload, raw)
        if (
            hashes[role] != sha256(raw).hexdigest()
        ):
            raise Task11ReadinessError(
                f"readiness evidence drift: {role}"
            )
    reviewed_manifest_sha256 = _required_reviewed_manifest_sha256(saved)
    if (
        reviewed_manifest_sha256 != hashes["candidate_manifest"]
        or reviewed_manifest_sha256 != expected_manifest_sha256
    ):
        raise Task11ReadinessError(
            "candidate manifest reviewed SHA-256 is invalid"
        )
    if fixture_bundle_verifier is None:
        for role in ("desktop_summary", "mobile_summary"):
            _verify_fixture_summary_bundles(
                Path(str(files[role])),
                summary=evidence_reads[role][0],
            )
    else:
        for role in ("desktop_summary", "mobile_summary"):
            fixture_bundle_verifier(Path(str(files[role])))
    manifest, root = _validated_manifest(
        Path(str(files["candidate_manifest"])),
        expected_manifest_sha256=reviewed_manifest_sha256,
    )
    _require_candidate_readiness_path(
        manifest_file=Path(str(files["candidate_manifest"])),
        manifest=manifest,
        readiness_path=Path(readiness_path),
    )
    canonical_ledger_path = _canonical_manifest_ledger_path(
        root=root,
        manifest=manifest,
    )
    if (
        saved.get("ledger_path") != str(canonical_ledger_path)
        or Path(ledger_path).absolute() != canonical_ledger_path
    ):
        raise Task11ReadinessError(
            "readiness canonical ledger path is invalid"
        )
    required_candidate_head = (
        _git_head(root)
        if expected_candidate_head is None
        else _git_commit(root, expected_candidate_head)
    )
    if manifest.get("candidate_head") != required_candidate_head:
        raise Task11ReadinessError("candidate HEAD drift")
    missing = tuple(
        path
        for path in discover_relevant_changes(root)
        if path
        not in {
            *manifest["protected_paths"],
            *manifest["deleted_paths"],
        }
    )
    if missing:
        raise Task11ReadinessError(
            "relevant changed paths missing from Task 11 Files: "
            + ", ".join(missing)
        )
    return verify_saved_readiness(
        readiness_path=readiness_path,
        manifest_path=files["candidate_manifest"],
        expected_manifest_sha256=reviewed_manifest_sha256,
        semantic_summary_path=files["semantic_summary"],
        zero_api_summary_path=files["zero_api_summary"],
        network_report_path=files["network_report"],
        runtime_network_report_path=files[
            "runtime_network_report"
        ],
        single_path_architecture_path=files[
            "single_path_architecture"
        ],
        test_path_audit_path=files["test_path_audit"],
        production_path_summary_path=files[
            "production_path_summary"
        ],
        independent_audit_path=files["independent_audit"],
        desktop_summary_path=files["desktop_summary"],
        mobile_summary_path=files["mobile_summary"],
        ledger_path=ledger_path,
        _evidence_reads={
            role: evidence_reads[role]
            for role in evidence_reads
            if role != "candidate_manifest"
        },
    )


def _verify_fixture_summary_bundles(
    summary_path: Path,
    *,
    summary: Mapping[str, object] | None = None,
) -> None:
    from tools.guide_gates.run_mainline_contract_browser_audit import (
        validate_audit_bundle,
    )

    summary_payload = (
        _read_evidence_object_once(
            summary_path,
            label="fixture summary",
        )[0]
        if summary is None
        else dict(summary)
    )
    _verify_fixture_artifact_index(
        summary_path,
        summary=summary_payload,
    )
    turns = summary_payload.get("turns")
    if not isinstance(turns, list):
        raise Task11ReadinessError("fixture summary is invalid")
    for expected_turn_id, row in zip(
        _FIXTURE_TURN_IDS,
        turns,
        strict=True,
    ):
        if (
            not isinstance(row, dict)
            or row.get("turn_id") != expected_turn_id
            or row.get("directory") != expected_turn_id
        ):
            raise Task11ReadinessError("fixture summary is invalid")
        try:
            validate_audit_bundle(
                summary_path.parent / expected_turn_id,
                expected_turn_id=expected_turn_id,
            )
        except ValueError as exc:
            raise Task11ReadinessError(
                f"fixture bundle failed: {expected_turn_id}"
            ) from exc


def finalize_change_manifest(
    *,
    repo_root: str | Path,
    draft_path: str | Path,
    candidate_manifest_path: str | Path,
    candidate_readiness_path: str | Path,
    expected_manifest_sha256: str,
    ledger_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    draft_file = Path(draft_path)
    draft = _read_object(draft_file, label="change manifest draft")
    candidate_file = Path(candidate_manifest_path)
    readiness_file = Path(candidate_readiness_path)
    output = Path(output_path)
    if output.exists() or output.is_symlink():
        raise Task11ReadinessError(
            f"change manifest already exists: {output}"
        )
    approved_raw = draft.get("approved_paths")
    context_relative = draft.get("attempt_context_path")
    bounded_attempt_id = draft.get("bounded_attempt_id")
    if (
        not isinstance(context_relative, str)
        or not context_relative
        or not isinstance(bounded_attempt_id, str)
        or not bounded_attempt_id
    ):
        raise Task11ReadinessError(
            "bounded attempt context is invalid"
        )
    context_file = (root / context_relative).resolve()
    if _repository_relative(root, context_file) != context_relative:
        raise Task11ReadinessError(
            "bounded attempt context is invalid"
        )
    candidate, candidate_root = _validated_manifest(
        candidate_file,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if candidate_root != root:
        raise Task11ReadinessError("candidate repository root mismatch")
    ledger_file = Path(ledger_path).resolve()
    ledger_relative = _repository_relative(root, ledger_file)
    candidate_readiness = verify_task11_readiness(
        readiness_path=readiness_file,
        ledger_path=ledger_file,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    (
        verified_attempt_id,
        bounded_artifact_paths,
        current_anchor,
    ) = _validated_bounded_attempt_artifacts(
        root=root,
        readiness_file=readiness_file,
        context_file=context_file,
        ledger_file=ledger_file,
    )
    expected_ledger_revision = draft.get("final_ledger_revision")
    expected_ledger_hash = draft.get("final_ledger_hash")
    if (
        draft.get("schema_version")
        != "guide-task11-change-manifest-v1"
        or not isinstance(approved_raw, list)
        or not approved_raw
        or draft.get("finalized") is not False
        or draft.get("staged_diff_sha256") is not None
        or draft.get("ledger_path") != ledger_relative
        or type(expected_ledger_revision) is not int
        or expected_ledger_revision < 0
        or not isinstance(expected_ledger_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_ledger_hash) is None
    ):
        raise Task11ReadinessError("change manifest is invalid")
    if (
        current_anchor["revision"] != expected_ledger_revision
        or current_anchor["revision_hash"] != expected_ledger_hash
    ):
        raise Task11ReadinessError(
            "ledger advanced after change manifest draft"
        )
    if (
        draft.get("plan_revision") != candidate["plan_revision"]
        or draft.get("candidate_manifest_sha256")
        != expected_manifest_sha256
        or draft.get("candidate_readiness_sha256")
        != sha256(readiness_file.read_bytes()).hexdigest()
        or candidate_readiness.get("schema_version")
        != _READINESS_SCHEMA
        or candidate_readiness.get("plan_revision")
        != candidate["plan_revision"]
        or candidate_readiness.get("protected_payload_sha256")
        != candidate["protected_payload_sha256"]
    ):
        raise Task11ReadinessError(
            "change manifest candidate binding is invalid"
        )
    approved = tuple(_normalized_path(str(item)) for item in approved_raw)
    if len(approved) != len(set(approved)):
        raise Task11ReadinessError("change manifest paths are invalid")
    fixture_artifact_paths = _readiness_fixture_artifact_paths(
        root=root,
        readiness=candidate_readiness,
    )
    bounded_raw = draft.get("bounded_artifact_paths")
    if (
        not isinstance(bounded_raw, list)
        or bounded_raw != sorted(set(bounded_raw))
        or bounded_raw != list(bounded_artifact_paths)
        or bounded_attempt_id != verified_attempt_id
    ):
        raise Task11ReadinessError(
            "change manifest bounded attempt binding is invalid"
        )
    evidence_files = candidate_readiness.get("evidence_files")
    if not isinstance(evidence_files, dict):
        raise Task11ReadinessError(
            "readiness evidence binding is invalid"
        )
    expected_approved = {
        *candidate["change_paths"],
        _repository_relative(root, candidate_file),
        _repository_relative(root, readiness_file),
        ledger_relative,
        context_relative,
        *(
            _repository_relative(root, Path(str(path)))
            for path in evidence_files.values()
        ),
        *fixture_artifact_paths,
        *bounded_artifact_paths,
    }
    if (
        draft.get("fixture_artifact_paths")
        != list(fixture_artifact_paths)
        or set(approved) != expected_approved
    ):
        raise Task11ReadinessError(
            "change manifest approved path set is invalid"
        )
    staged_output = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--name-status",
            "--no-renames",
            "-z",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    fields = [
        item.decode("utf-8")
        for item in staged_output.split(b"\0")
        if item
    ]
    if len(fields) % 2:
        raise Task11ReadinessError("staged status rows are invalid")
    staged_status = {
        fields[index + 1]: fields[index]
        for index in range(0, len(fields), 2)
    }
    if set(staged_status) != set(approved):
        raise Task11ReadinessError("staged path set mismatch")
    if ledger_relative not in staged_status:
        raise Task11ReadinessError("staged ledger is missing")
    deleted = set(candidate["deleted_paths"])
    if any(
        (
            status != "D"
            if path in deleted
            else status not in {"A", "M"}
        )
        for path, status in staged_status.items()
    ):
        raise Task11ReadinessError("staged path status mismatch")
    staged_ledger = subprocess.run(
        ["git", "show", f":{ledger_relative}"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if staged_ledger.returncode != 0:
        raise Task11ReadinessError("staged ledger is unavailable")
    if staged_ledger.stdout != ledger_file.read_bytes():
        raise Task11ReadinessError(
            "staged ledger differs from worktree ledger"
        )
    try:
        staged_ledger_payload = json.loads(staged_ledger.stdout)
        if not isinstance(staged_ledger_payload, dict):
            raise ValueError("ledger is not an object")
        staged_anchor = ledger_anchor(staged_ledger_payload)
    except (ValueError, json.JSONDecodeError) as exc:
        raise Task11ReadinessError("staged ledger is invalid") from exc
    if (
        staged_anchor["revision"] != expected_ledger_revision
        or staged_anchor["revision_hash"] != expected_ledger_hash
    ):
        raise Task11ReadinessError(
            "staged ledger tip does not match change manifest draft"
        )
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--binary",
            "--",
            *approved,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    finalized = {
        **draft,
        "approved_paths": list(approved),
        "staged_diff_sha256": sha256(diff).hexdigest(),
        "finalized": True,
    }
    _write_json_exclusive(
        output,
        finalized,
        label="change manifest",
    )
    return finalized


def _repository_relative(root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise Task11ReadinessError(
            "change manifest path escapes repository"
        ) from exc
    return _normalized_path(relative)


def _validate_completed_bounded_evidence(
    attempt_directory: Path,
) -> None:
    from tools.guide_gates.run_mainline_contract_browser_audit import (
        AuditBundleError,
        validate_completed_bounded_browser_evidence,
    )

    try:
        validate_completed_bounded_browser_evidence(attempt_directory)
    except (AuditBundleError, OSError, ValueError) as exc:
        raise Task11ReadinessError(
            "bounded browser evidence is invalid"
        ) from exc


def _validated_bounded_attempt_artifacts(
    *,
    root: Path,
    readiness_file: Path,
    context_file: Path,
    ledger_file: Path,
) -> tuple[str, tuple[str, ...], dict[str, object]]:
    context_relative = _repository_relative(root, context_file)
    context = read_attempt_context(
        context_file,
        ledger_path=ledger_file,
        readiness_path=readiness_file,
    )
    phase_ids = context.get("phase_attempt_ids")
    if not isinstance(phase_ids, dict):
        raise Task11ReadinessError("bounded attempt context is invalid")
    attempt_id = phase_ids.get("bounded")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise Task11ReadinessError("bounded attempt context is invalid")
    ledger = read_ledger(ledger_file)
    final_ledger_anchor = ledger_anchor(ledger)
    attempts = ledger.get("attempts")
    matching = [
        item
        for item in attempts
        if isinstance(item, dict)
        and item.get("attempt_id") == attempt_id
    ] if isinstance(attempts, list) else []
    if len(matching) != 1 or matching[0].get("result") != "passed":
        raise Task11ReadinessError("bounded attempt has not passed")
    attempt_dir = Path(str(context.get("output_directory"))).resolve()
    _repository_relative(root, attempt_dir)
    if not attempt_dir.is_dir():
        raise Task11ReadinessError(
            "bounded attempt directory is missing"
        )
    _validate_completed_bounded_evidence(attempt_dir)
    try:
        validate_runtime_bound_attempt_attestation(
            context_path=context_file,
            context=context,
            attempt=matching[0],
            ledger=ledger,
            require_browser_summary=True,
        )
    except AttemptLedgerError as exc:
        raise Task11ReadinessError(
            "bounded runtime attestation is invalid"
        ) from exc
    artifact_paths: list[str] = []
    for item in sorted(attempt_dir.rglob("*")):
        if item.is_symlink():
            raise Task11ReadinessError(
                "bounded artifact path is a symlink"
            )
        if item.is_file():
            artifact_paths.append(_repository_relative(root, item))
    if context_relative not in artifact_paths:
        raise Task11ReadinessError(
            "bounded attempt context is outside its artifact directory"
        )
    return attempt_id, tuple(artifact_paths), final_ledger_anchor


def build_change_manifest(
    *,
    candidate_manifest_path: str | Path,
    candidate_readiness_path: str | Path,
    attempt_context_path: str | Path,
    expected_manifest_sha256: str,
    ledger_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    candidate_file = Path(candidate_manifest_path)
    readiness_file = Path(candidate_readiness_path)
    manifest, root = _validated_manifest(
        candidate_file,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    verified = verify_task11_readiness(
        readiness_path=readiness_file,
        ledger_path=ledger_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if (
        verified.get("plan_revision") != manifest["plan_revision"]
        or verified.get("protected_payload_sha256")
        != manifest["protected_payload_sha256"]
    ):
        raise Task11ReadinessError(
            "candidate readiness does not match manifest"
        )
    context_path = Path(attempt_context_path).resolve()
    ledger_file = Path(ledger_path).resolve()
    (
        attempt_id,
        artifact_paths,
        final_ledger_anchor,
    ) = _validated_bounded_attempt_artifacts(
        root=root,
        readiness_file=readiness_file,
        context_file=context_path,
        ledger_file=ledger_file,
    )
    evidence_files = verified.get("evidence_files")
    if not isinstance(evidence_files, dict):
        raise Task11ReadinessError("readiness evidence binding is invalid")
    fixture_artifact_paths = _readiness_fixture_artifact_paths(
        root=root,
        readiness=verified,
    )
    supporting = {
        _repository_relative(root, candidate_file),
        _repository_relative(root, readiness_file),
        _repository_relative(root, Path(ledger_path)),
        _repository_relative(root, context_path),
        *(
            _repository_relative(root, Path(str(path)))
            for path in evidence_files.values()
        ),
        *fixture_artifact_paths,
        *artifact_paths,
    }
    approved = tuple(sorted({
        *manifest["change_paths"],
        *supporting,
    }))
    output = {
        "schema_version": "guide-task11-change-manifest-v1",
        "plan_revision": manifest["plan_revision"],
        "candidate_manifest_sha256": expected_manifest_sha256,
        "candidate_readiness_sha256": sha256(
            readiness_file.read_bytes()
        ).hexdigest(),
        "bounded_attempt_id": attempt_id,
        "attempt_context_path": _repository_relative(root, context_path),
        "bounded_artifact_paths": list(artifact_paths),
        "fixture_artifact_paths": list(fixture_artifact_paths),
        "ledger_path": _repository_relative(root, ledger_file),
        "final_ledger_revision": final_ledger_anchor["revision"],
        "final_ledger_hash": final_ledger_anchor["revision_hash"],
        "approved_paths": list(approved),
        "staged_diff_sha256": None,
        "finalized": False,
    }
    _write_json_exclusive(
        Path(output_path),
        output,
        label="change manifest draft",
    )
    return output


def _git_commit(root: Path, revision: str) -> str:
    if (
        not isinstance(revision, str)
        or _HEX_40_PATTERN.fullmatch(revision) is None
    ):
        raise Task11ReadinessError("Task 11 commit is invalid")
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    resolved = completed.stdout.strip()
    if completed.returncode != 0 or resolved != revision:
        raise Task11ReadinessError("Task 11 commit is invalid")
    return resolved


def _git_commit_parent(root: Path, revision: str) -> str:
    completed = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", revision],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    parts = completed.stdout.strip().split()
    if len(parts) != 2 or parts[0] != revision:
        raise Task11ReadinessError(
            "Task 11 commit must have exactly one parent"
        )
    return parts[1]


def _git_tree_oid(root: Path, revision: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", f"{revision}^{{tree}}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _canonical_git_payload_sha256(
    root: Path,
    *,
    revision: str,
    paths: Sequence[str],
) -> str:
    digest = sha256()
    for raw_path in sorted(paths):
        relative = _normalized_path(raw_path)
        content = _git_blob(root, revision=revision, path=relative)
        encoded_path = relative.encode("utf-8")
        digest.update(str(len(encoded_path)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded_path)
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b":")
        digest.update(content)
    return digest.hexdigest()


def _git_name_status(
    root: Path,
    *,
    base: str,
    revision: str,
) -> dict[str, str]:
    output = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "--no-renames",
            "-z",
            base,
            revision,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    fields = [
        item.decode("utf-8")
        for item in output.split(b"\0")
        if item
    ]
    if len(fields) % 2:
        raise Task11ReadinessError(
            "Task 11 commit status rows are invalid"
        )
    return {
        fields[index + 1]: fields[index]
        for index in range(0, len(fields), 2)
    }


def _release_execution_inventory(
    root: Path,
    *,
    revision: str,
) -> tuple[tuple[str, ...], dict[str, str]]:
    output = subprocess.run(
        [
            "git",
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            revision,
            "--",
            "app",
            "tools",
            "tests",
            *_TASK12_RUNTIME_DATA_PATHS,
            *_RELEASE_PLAN_PATHS,
            *_RELEVANT_ROOT_FILES,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    hashes: dict[str, str] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, _ = metadata.decode("ascii").split()
            path = _normalized_path(raw_path.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise Task11ReadinessError(
                "release execution tree is invalid"
            ) from exc
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise Task11ReadinessError(
                f"release execution path is not a regular blob: {path}"
            )
        hashes[path] = sha256(
            _git_blob(root, revision=revision, path=path)
        ).hexdigest()
    paths = tuple(sorted(hashes))
    if not set(_RELEASE_PLAN_PATHS) <= set(paths):
        raise Task11ReadinessError(
            "release execution tree omits a release plan"
        )
    return paths, hashes


def _require_clean_release_execution_tree(root: Path) -> None:
    status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            "app",
            "tools",
            "tests",
            *_TASK12_RUNTIME_DATA_PATHS,
            *_RELEASE_PLAN_PATHS,
            *_RELEVANT_ROOT_FILES,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    if status:
        raise Task11ReadinessError("release execution tree drift")


def seal_task11_commit(
    *,
    repo_root: str | Path,
    change_manifest_path: str | Path,
    candidate_readiness_path: str | Path,
    release_readiness_path: str | Path,
    task11_commit: str,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    commit = _git_commit(root, task11_commit)
    if _git_head(root) != commit:
        raise Task11ReadinessError("Task 11 commit must equal HEAD")
    parent = _git_commit_parent(root, commit)
    change_file = Path(change_manifest_path).resolve()
    candidate_readiness_file = Path(candidate_readiness_path).resolve()
    release_file = Path(release_readiness_path).resolve()
    change = _read_object(change_file, label="change manifest")
    ledger_relative = change.get("ledger_path")
    if not isinstance(ledger_relative, str):
        raise Task11ReadinessError("Task 11 change manifest is invalid")
    ledger_file = (root / ledger_relative).resolve()
    _repository_relative(root, ledger_file)
    candidate_readiness = verify_task11_readiness(
        readiness_path=candidate_readiness_file,
        ledger_path=ledger_file,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_candidate_head=parent,
    )
    evidence_files = candidate_readiness["evidence_files"]
    evidence_hashes = candidate_readiness["evidence_sha256"]
    candidate_file = Path(
        str(evidence_files["candidate_manifest"])
    ).resolve()
    candidate, candidate_root = _validated_manifest(
        candidate_file,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if candidate_root != root:
        raise Task11ReadinessError("candidate repository root mismatch")
    if (
        change.get("schema_version")
        != "guide-task11-change-manifest-v1"
        or change.get("finalized") is not True
        or change.get("plan_revision") != candidate["plan_revision"]
        or change.get("candidate_manifest_sha256")
        != expected_manifest_sha256
        or change.get("candidate_readiness_sha256")
        != sha256(candidate_readiness_file.read_bytes()).hexdigest()
        or candidate_readiness.get("plan_revision")
        != candidate["plan_revision"]
        or candidate_readiness.get("protected_payload_sha256")
        != candidate["protected_payload_sha256"]
        or parent != candidate["candidate_head"]
    ):
        raise Task11ReadinessError(
            "Task 11 change manifest binding is invalid"
        )
    approved_raw = change.get("approved_paths")
    if (
        not isinstance(approved_raw, list)
        or not approved_raw
        or approved_raw != sorted(set(approved_raw))
    ):
        raise Task11ReadinessError("Task 11 change paths are invalid")
    approved = tuple(_normalized_path(str(item)) for item in approved_raw)
    fixture_artifact_paths = _readiness_fixture_artifact_paths(
        root=root,
        readiness=candidate_readiness,
    )
    context_relative = change.get("attempt_context_path")
    if not isinstance(context_relative, str):
        raise Task11ReadinessError(
            "Task 11 bounded attempt context is invalid"
        )
    context_file = (root / context_relative).resolve()
    if _repository_relative(root, context_file) != context_relative:
        raise Task11ReadinessError(
            "Task 11 bounded attempt context is invalid"
        )
    (
        bounded_attempt_id,
        bounded_artifact_paths,
        bounded_ledger_anchor,
    ) = _validated_bounded_attempt_artifacts(
        root=root,
        readiness_file=candidate_readiness_file,
        context_file=context_file,
        ledger_file=ledger_file,
    )
    if (
        change.get("fixture_artifact_paths")
        != list(fixture_artifact_paths)
        or change.get("bounded_attempt_id") != bounded_attempt_id
        or change.get("bounded_artifact_paths")
        != list(bounded_artifact_paths)
        or not set(fixture_artifact_paths) <= set(approved)
    ):
        raise Task11ReadinessError(
            "Task 11 bounded or fixture artifact binding is invalid"
        )
    expected_approved = {
        *candidate["change_paths"],
        _repository_relative(root, candidate_file),
        _repository_relative(root, candidate_readiness_file),
        _repository_relative(root, ledger_file),
        context_relative,
        *(
            _repository_relative(root, Path(str(path)))
            for path in evidence_files.values()
        ),
        *fixture_artifact_paths,
        *bounded_artifact_paths,
    }
    if set(approved) != expected_approved:
        raise Task11ReadinessError(
            "Task 11 approved path set is invalid"
        )
    change_relative = _repository_relative(root, change_file)
    committed_status = _git_name_status(
        root,
        base=parent,
        revision=commit,
    )
    if set(committed_status) != {*approved, change_relative}:
        raise Task11ReadinessError(
            "Task 11 commit path set does not match change manifest"
        )
    deleted = set(candidate["deleted_paths"])
    if any(
        (
            status != "D"
            if path in deleted
            else status not in {"A", "M"}
        )
        for path, status in committed_status.items()
        if path != change_relative
    ) or committed_status.get(change_relative) not in {"A", "M"}:
        raise Task11ReadinessError(
            "Task 11 commit path status is invalid"
        )
    committed_diff = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            parent,
            commit,
            "--",
            *approved,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    if change.get("staged_diff_sha256") != sha256(
        committed_diff
    ).hexdigest():
        raise Task11ReadinessError(
            "Task 11 committed diff hash mismatch"
        )
    for path in (
        change_file,
        candidate_readiness_file,
        candidate_file,
        *(
            Path(str(value)).resolve()
            for value in evidence_files.values()
        ),
    ):
        relative = _repository_relative(root, path)
        if _git_blob(root, revision=commit, path=relative) != path.read_bytes():
            raise Task11ReadinessError(
                f"Task 11 committed evidence drift: {relative}"
            )
    fixture_artifact_hashes: dict[str, str] = {}
    for relative in fixture_artifact_paths:
        path = root / relative
        try:
            committed = _git_blob(
                root,
                revision=commit,
                path=relative,
            )
        except Task11ReadinessError as exc:
            raise Task11ReadinessError(
                f"Task 11 committed fixture artifact is missing: {relative}"
            ) from exc
        current = path.read_bytes()
        if committed != current:
            raise Task11ReadinessError(
                f"Task 11 committed fixture artifact drift: {relative}"
            )
        fixture_artifact_hashes[relative] = sha256(current).hexdigest()
    protected_paths = tuple(candidate["protected_paths"])
    protected_hashes = {
        path: sha256(
            _git_blob(root, revision=commit, path=path)
        ).hexdigest()
        for path in protected_paths
    }
    protected_payload = _canonical_git_payload_sha256(
        root,
        revision=commit,
        paths=protected_paths,
    )
    if protected_payload != candidate["protected_payload_sha256"]:
        raise Task11ReadinessError(
            "Task 11 committed protected payload drift"
        )
    ledger = read_ledger(ledger_file)
    anchor = ledger_anchor(ledger)
    if (
        anchor != bounded_ledger_anchor
        or anchor["revision"] != change.get("final_ledger_revision")
        or anchor["revision_hash"] != change.get("final_ledger_hash")
        or _current_circuit_state(
            ledger,
            plan_revision=candidate["plan_revision"],
        )
        != "closed"
    ):
        raise Task11ReadinessError(
            "Task 11 final ledger binding is invalid"
        )
    execution_paths, execution_hashes = _release_execution_inventory(
        root,
        revision=commit,
    )
    _require_clean_release_execution_tree(root)
    execution_payload = _canonical_git_payload_sha256(
        root,
        revision=commit,
        paths=execution_paths,
    )
    release = {
        **candidate_readiness,
        "schema_version": _RELEASE_READINESS_SCHEMA,
        "candidate_head": commit,
        "task11_commit": commit,
        "candidate_base_head": candidate["candidate_head"],
        "task11_parent_commit": parent,
        "task11_tree_oid": _git_tree_oid(root, commit),
        "candidate_payload_sha256": protected_payload,
        "protected_payload_sha256": protected_payload,
        "protected_paths": list(protected_paths),
        "protected_blob_sha256_by_path": protected_hashes,
        "release_plan_paths": list(_RELEASE_PLAN_PATHS),
        "release_execution_paths": list(execution_paths),
        "release_execution_blob_sha256_by_path": execution_hashes,
        "release_execution_tree_sha256": execution_payload,
        "change_manifest_path": str(change_file),
        "change_manifest_sha256": sha256(
            change_file.read_bytes()
        ).hexdigest(),
        "candidate_readiness_path": str(candidate_readiness_file),
        "candidate_readiness_sha256": sha256(
            candidate_readiness_file.read_bytes()
        ).hexdigest(),
        "candidate_manifest_path": str(candidate_file),
        "candidate_manifest_sha256": expected_manifest_sha256,
        "fixture_artifact_paths": list(fixture_artifact_paths),
        "fixture_artifact_sha256_by_path": fixture_artifact_hashes,
        "ledger_path": str(ledger_file),
        "ledger_anchor_revision": anchor["revision"],
        "ledger_anchor_hash": anchor["revision_hash"],
        "circuit_state": "closed",
    }
    _write_json_exclusive(
        release_file,
        release,
        label="release readiness",
    )
    return release


def verify_release_readiness(
    *,
    readiness_path: str | Path,
    require_head: str,
    expected_manifest_sha256: str,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    readiness_file = Path(readiness_path).resolve()
    saved = _read_object(readiness_file, label="release readiness")
    if saved.get("schema_version") != _RELEASE_READINESS_SCHEMA:
        raise Task11ReadinessError("release readiness is invalid")
    task11_commit = _git_commit(
        Path(str(saved.get("candidate_manifest_path"))).resolve().parent,
        str(saved.get("task11_commit")),
    )
    candidate_file = Path(
        str(saved.get("candidate_manifest_path"))
    ).resolve()
    candidate, root = _validated_manifest(
        candidate_file,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if (
        _required_reviewed_manifest_sha256(saved)
        != expected_manifest_sha256
    ):
        raise Task11ReadinessError(
            "candidate manifest reviewed SHA-256 is invalid"
        )
    task11_commit = _git_commit(root, task11_commit)
    if (
        require_head != task11_commit
        or _git_head(root) != task11_commit
        or saved.get("candidate_head") != task11_commit
        or saved.get("task11_parent_commit")
        != _git_commit_parent(root, task11_commit)
        or saved.get("task11_tree_oid")
        != _git_tree_oid(root, task11_commit)
        or saved.get("candidate_base_head")
        != candidate["candidate_head"]
    ):
        raise Task11ReadinessError(
            "release readiness commit binding is invalid"
        )
    change_file = Path(str(saved.get("change_manifest_path"))).resolve()
    candidate_readiness_file = Path(
        str(saved.get("candidate_readiness_path"))
    ).resolve()
    if (
        saved.get("change_manifest_sha256")
        != sha256(change_file.read_bytes()).hexdigest()
        or saved.get("candidate_readiness_sha256")
        != sha256(candidate_readiness_file.read_bytes()).hexdigest()
        or saved.get("candidate_manifest_sha256")
        != expected_manifest_sha256
    ):
        raise Task11ReadinessError(
            "release readiness source evidence drift"
        )
    for path in (
        change_file,
        candidate_readiness_file,
        candidate_file,
    ):
        relative = _repository_relative(root, path)
        if (
            _git_blob(root, revision=task11_commit, path=relative)
            != path.read_bytes()
        ):
            raise Task11ReadinessError(
                f"release readiness committed evidence drift: {relative}"
            )
    protected_paths = tuple(
        str(path) for path in saved.get("protected_paths", ())
    )
    execution_paths = tuple(
        str(path) for path in saved.get("release_execution_paths", ())
    )
    current_execution_paths, execution_hashes = (
        _release_execution_inventory(
            root,
            revision=task11_commit,
        )
    )
    if (
        protected_paths != tuple(candidate["protected_paths"])
        or saved.get("protected_blob_sha256_by_path")
        != {
            path: sha256(
                _git_blob(root, revision=task11_commit, path=path)
            ).hexdigest()
            for path in protected_paths
        }
        or saved.get("protected_payload_sha256")
        != _canonical_git_payload_sha256(
            root,
            revision=task11_commit,
            paths=protected_paths,
        )
        or execution_paths != current_execution_paths
        or saved.get("release_execution_blob_sha256_by_path")
        != execution_hashes
        or saved.get("release_execution_tree_sha256")
        != _canonical_git_payload_sha256(
            root,
            revision=task11_commit,
            paths=execution_paths,
        )
    ):
        raise Task11ReadinessError("release execution tree is invalid")
    _require_clean_release_execution_tree(root)
    saved_ledger = Path(str(saved.get("ledger_path"))).resolve()
    if (
        ledger_path is not None
        and Path(ledger_path).resolve() != saved_ledger
    ):
        raise Task11ReadinessError("release readiness ledger mismatch")
    try:
        verify_ledger_extension(
            read_ledger(saved_ledger),
            anchor_revision=saved.get("ledger_anchor_revision"),
            anchor_hash=saved.get("ledger_anchor_hash"),
        )
    except ValueError as exc:
        raise Task11ReadinessError(
            "release readiness ledger anchor is invalid"
        ) from exc
    verified_candidate = verify_task11_readiness(
        readiness_path=candidate_readiness_file,
        ledger_path=saved_ledger,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_candidate_head=str(saved.get("candidate_base_head")),
    )
    release_overrides = {
        "schema_version",
        "candidate_head",
        "ledger_anchor_revision",
        "ledger_anchor_hash",
    }
    if any(
        saved.get(key) != value
        for key, value in verified_candidate.items()
        if key not in release_overrides
    ):
        raise Task11ReadinessError(
            "release readiness candidate readiness derivation mismatch"
        )
    evidence_files = saved.get("evidence_files")
    evidence_hashes = saved.get("evidence_sha256")
    if (
        not isinstance(evidence_files, dict)
        or not isinstance(evidence_hashes, dict)
        or set(evidence_files) != set(evidence_hashes)
    ):
        raise Task11ReadinessError(
            "release readiness evidence binding is invalid"
        )
    for role, raw_path in evidence_files.items():
        evidence_path = Path(str(raw_path))
        if (
            not evidence_path.is_file()
            or evidence_hashes.get(role)
            != sha256(evidence_path.read_bytes()).hexdigest()
        ):
            raise Task11ReadinessError(
                f"release readiness evidence drift: {role}"
            )
    fixture_artifact_paths = _readiness_fixture_artifact_paths(
        root=root,
        readiness=saved,
    )
    fixture_artifact_hashes = saved.get(
        "fixture_artifact_sha256_by_path"
    )
    if (
        saved.get("fixture_artifact_paths")
        != list(fixture_artifact_paths)
        or not isinstance(fixture_artifact_hashes, dict)
        or set(fixture_artifact_hashes) != set(fixture_artifact_paths)
    ):
        raise Task11ReadinessError(
            "release readiness fixture artifact binding is invalid"
        )
    for relative in fixture_artifact_paths:
        path = root / relative
        expected_hash = fixture_artifact_hashes.get(relative)
        try:
            committed = _git_blob(
                root,
                revision=task11_commit,
                path=relative,
            )
        except Task11ReadinessError as exc:
            raise Task11ReadinessError(
                f"release fixture artifact is missing: {relative}"
            ) from exc
        if (
            expected_hash != sha256(path.read_bytes()).hexdigest()
            or expected_hash != sha256(committed).hexdigest()
        ):
            raise Task11ReadinessError(
                f"release fixture artifact drift: {relative}"
            )
    return saved


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit-test-paths")
    audit.add_argument("--repo-root", type=Path, default=Path.cwd())
    audit.add_argument("--plan", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--repo-root", type=Path, default=Path.cwd())
    manifest.add_argument("--plan", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument(
        "--fixture-runtime-private-key",
        type=Path,
        required=True,
    )
    prepare_manifest = subparsers.add_parser("prepare-manifest")
    prepare_manifest.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
    )
    prepare_manifest.add_argument("--plan", type=Path, required=True)
    prepare_manifest.add_argument(
        "--test-path-audit",
        type=Path,
        required=True,
    )
    prepare_manifest.add_argument(
        "--manifest",
        type=Path,
        required=True,
    )
    prepare_manifest.add_argument(
        "--fixture-runtime-private-key",
        type=Path,
        required=True,
    )
    prepare = subparsers.add_parser("prepare-evidence")
    prepare.add_argument("--repo-root", type=Path, default=Path.cwd())
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    prepare.add_argument(
        "--semantic-summary-output",
        type=Path,
        required=True,
    )
    prepare.add_argument(
        "--zero-api-summary-output",
        type=Path,
        required=True,
    )
    prepare.add_argument(
        "--network-report-output",
        type=Path,
        required=True,
    )
    prepare.add_argument(
        "--single-path-architecture",
        type=Path,
        required=True,
    )
    prepare.add_argument("--test-path-audit", type=Path, required=True)
    prepare.add_argument(
        "--production-path-summary",
        type=Path,
        required=True,
    )
    prepare.add_argument(
        "--cases",
        type=Path,
        default=Path(
            "tests/fixtures/guide/intent/"
            "turn_meaning_gate_v1.jsonl"
        ),
    )
    promote = subparsers.add_parser("promote-runtime-browser-evidence")
    promote.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
    )
    promote.add_argument("--manifest", type=Path, required=True)
    promote.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    promote.add_argument("--attempt-root", type=Path, required=True)
    promote.add_argument(
        "--fixture-runtime-private-key",
        type=Path,
        required=True,
    )
    seal_readiness = subparsers.add_parser("seal-readiness")
    seal_readiness.add_argument("--manifest", type=Path, required=True)
    seal_readiness.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    seal_readiness.add_argument(
        "--readiness",
        type=Path,
        required=True,
    )
    seal_readiness.add_argument(
            "--semantic-summary",
            type=Path,
            required=True,
        )
    seal_readiness.add_argument(
            "--zero-api-summary",
            type=Path,
            required=True,
        )
    seal_readiness.add_argument(
            "--network-report",
            type=Path,
            required=True,
        )
    seal_readiness.add_argument(
            "--runtime-network-report",
            type=Path,
            required=True,
        )
    seal_readiness.add_argument(
            "--single-path-architecture",
            type=Path,
            required=True,
        )
    seal_readiness.add_argument(
            "--test-path-audit",
            type=Path,
            required=True,
        )
    seal_readiness.add_argument(
            "--production-path-summary",
            type=Path,
            required=True,
        )
    seal_readiness.add_argument(
            "--independent-audit",
            type=Path,
            required=True,
        )
    seal_readiness.add_argument(
            "--desktop-summary",
            type=Path,
            required=True,
        )
    seal_readiness.add_argument(
            "--mobile-summary",
            type=Path,
            required=True,
        )
    seal_readiness.add_argument("--ledger", type=Path, required=True)
    seal_readiness.add_argument(
        "--fixture-runtime-private-key",
        type=Path,
        required=True,
    )
    finalize = subparsers.add_parser("finalize-change-manifest")
    finalize.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
    )
    finalize.add_argument("--draft", type=Path, required=True)
    finalize.add_argument(
        "--candidate-manifest",
        type=Path,
        required=True,
    )
    finalize.add_argument(
        "--candidate-readiness",
        type=Path,
        required=True,
    )
    finalize.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    finalize.add_argument("--ledger", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    change = subparsers.add_parser("build-change-manifest")
    change.add_argument(
        "--candidate-manifest",
        type=Path,
        required=True,
    )
    change.add_argument(
        "--candidate-readiness",
        type=Path,
        required=True,
    )
    change.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    change.add_argument(
        "--attempt-context",
        type=Path,
        required=True,
    )
    change.add_argument("--ledger", type=Path, required=True)
    change.add_argument("--output", type=Path, required=True)
    commit_seal = subparsers.add_parser("seal-commit")
    commit_seal.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
    )
    commit_seal.add_argument("--manifest", type=Path, required=True)
    commit_seal.add_argument(
        "--candidate-readiness",
        type=Path,
        required=True,
    )
    commit_seal.add_argument(
        "--release-readiness",
        type=Path,
        required=True,
    )
    commit_seal.add_argument("--task11-commit", required=True)
    commit_seal.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    verify_release = subparsers.add_parser(
        "verify-release-readiness"
    )
    verify_release.add_argument(
        "--readiness",
        type=Path,
        required=True,
    )
    verify_release.add_argument("--require-head", required=True)
    verify_release.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "audit-test-paths":
        result = build_test_path_audit(
            repo_root=args.repo_root,
            plan_path=args.plan,
            output_path=args.output,
        )
    elif args.command == "manifest":
        result = build_candidate_manifest(
            repo_root=args.repo_root,
            plan_path=args.plan,
            output_path=args.output,
            fixture_runtime_private_key_path=(
                args.fixture_runtime_private_key
            ),
        )
    elif args.command == "prepare-manifest":
        result = build_candidate_manifest(
            repo_root=args.repo_root,
            plan_path=args.plan,
            output_path=args.manifest,
            test_path_audit_path=args.test_path_audit,
            fixture_runtime_private_key_path=(
                args.fixture_runtime_private_key
            ),
        )
    elif args.command == "prepare-evidence":
        result = prepare_task11_evidence(
            repo_root=args.repo_root,
            manifest_path=args.manifest,
            expected_manifest_sha256=(
                args.expected_manifest_sha256
            ),
            semantic_summary_path=args.semantic_summary_output,
            zero_api_summary_path=args.zero_api_summary_output,
            network_report_path=args.network_report_output,
            single_path_architecture_path=(
                args.single_path_architecture
            ),
            test_path_audit_path=args.test_path_audit,
            production_path_summary_path=(
                args.production_path_summary
            ),
            cases_path=args.cases,
        )
    elif args.command == "promote-runtime-browser-evidence":
        result = promote_runtime_browser_evidence(
            repo_root=args.repo_root,
            manifest_path=args.manifest,
            expected_manifest_sha256=(
                args.expected_manifest_sha256
            ),
            attempt_root=args.attempt_root,
            fixture_runtime_private_key_path=(
                args.fixture_runtime_private_key
            ),
        )
    elif args.command == "seal-readiness":
        result = seal_candidate_readiness(
            manifest_path=args.manifest,
            expected_manifest_sha256=(
                args.expected_manifest_sha256
            ),
            semantic_summary_path=args.semantic_summary,
            zero_api_summary_path=args.zero_api_summary,
            network_report_path=args.network_report,
            runtime_network_report_path=(
                args.runtime_network_report
            ),
            single_path_architecture_path=(
                args.single_path_architecture
            ),
            test_path_audit_path=args.test_path_audit,
            production_path_summary_path=(
                args.production_path_summary
            ),
            independent_audit_path=args.independent_audit,
            desktop_summary_path=args.desktop_summary,
            mobile_summary_path=args.mobile_summary,
            ledger_path=args.ledger,
            output_path=args.readiness,
            fixture_runtime_private_key_path=(
                args.fixture_runtime_private_key
            ),
        )
    elif args.command == "finalize-change-manifest":
        result = finalize_change_manifest(
            repo_root=args.repo_root,
            draft_path=args.draft,
            candidate_manifest_path=args.candidate_manifest,
            candidate_readiness_path=args.candidate_readiness,
            expected_manifest_sha256=(
                args.expected_manifest_sha256
            ),
            ledger_path=args.ledger,
            output_path=args.output,
        )
    elif args.command == "build-change-manifest":
        result = build_change_manifest(
            candidate_manifest_path=args.candidate_manifest,
            candidate_readiness_path=args.candidate_readiness,
            attempt_context_path=args.attempt_context,
            expected_manifest_sha256=(
                args.expected_manifest_sha256
            ),
            ledger_path=args.ledger,
            output_path=args.output,
        )
    elif args.command == "seal-commit":
        result = seal_task11_commit(
            repo_root=args.repo_root,
            change_manifest_path=args.manifest,
            candidate_readiness_path=args.candidate_readiness,
            release_readiness_path=args.release_readiness,
            task11_commit=args.task11_commit,
            expected_manifest_sha256=(
                args.expected_manifest_sha256
            ),
        )
    else:
        result = verify_release_readiness(
            readiness_path=args.readiness,
            require_head=args.require_head,
            expected_manifest_sha256=(
                args.expected_manifest_sha256
            ),
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
