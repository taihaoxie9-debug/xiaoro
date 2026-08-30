"""Asymmetric proof primitives for an attempt-bound Guide runtime."""

from __future__ import annotations

import base64
from collections.abc import Mapping
import json
import re
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


RuntimePhase = Literal["bounded", "browser"]
PROOF_REQUEST_SCHEMA = "guide-bound-runtime-proof-request-v1"
PROOF_SCHEMA = "guide-bound-runtime-proof-v1"
_SIGNATURE_DOMAIN = b"xiaoro-guide-bound-runtime-proof-v1\x00"
_REQUEST_KEYS = frozenset({
    "schema_version",
    "registration_id",
    "phase",
    "attempt_id",
    "attempt_context_sha256",
    "readiness_sha256",
    "allocated_ledger_revision",
    "allocated_ledger_hash",
    "runtime_identity_sha256",
    "verifier_nonce",
})
_PROOF_KEYS = _REQUEST_KEYS | {"runtime_public_key", "signature"}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_REGISTRATION_ID_PATTERN = re.compile(r"runtime_[0-9a-f]{16,64}")


class RuntimeProofError(ValueError):
    """Raised when a runtime proof is malformed or unauthentic."""


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            dict(payload),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _encode_raw(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_raw(value: object, *, length: int, label: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise RuntimeProofError(f"runtime {label} is invalid")
    try:
        decoded = base64.b64decode(
            value + ("=" * (-len(value) % 4)),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise RuntimeProofError(f"runtime {label} is invalid") from exc
    if len(decoded) != length or _encode_raw(decoded) != value:
        raise RuntimeProofError(f"runtime {label} is invalid")
    return decoded


def _validated_request(
    request: Mapping[str, object],
) -> dict[str, object]:
    payload = dict(request)
    revision = payload.get("allocated_ledger_revision")
    if (
        set(payload) != _REQUEST_KEYS
        or payload.get("schema_version") != PROOF_REQUEST_SCHEMA
        or _REGISTRATION_ID_PATTERN.fullmatch(
            str(payload.get("registration_id"))
        )
        is None
        or payload.get("phase") not in {"bounded", "browser"}
        or not isinstance(payload.get("attempt_id"), str)
        or not payload["attempt_id"]
        or any(
            _SHA256_PATTERN.fullmatch(str(payload.get(field))) is None
            for field in (
                "attempt_context_sha256",
                "readiness_sha256",
                "allocated_ledger_hash",
                "runtime_identity_sha256",
                "verifier_nonce",
            )
        )
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 0
    ):
        raise RuntimeProofError("runtime proof request is invalid")
    return payload


def generate_runtime_keypair() -> tuple[Ed25519PrivateKey, str]:
    private_key = Ed25519PrivateKey.generate()
    return private_key, runtime_public_key(private_key)


def runtime_public_key(private_key: Ed25519PrivateKey) -> str:
    if not isinstance(private_key, Ed25519PrivateKey):
        raise RuntimeProofError("runtime private key is invalid")
    return _encode_raw(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )


def encode_runtime_private_key(
    private_key: Ed25519PrivateKey,
) -> str:
    if not isinstance(private_key, Ed25519PrivateKey):
        raise RuntimeProofError("runtime private key is invalid")
    return _encode_raw(
        private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def decode_runtime_private_key(value: object) -> Ed25519PrivateKey:
    raw = _decode_raw(value, length=32, label="private key")
    try:
        return Ed25519PrivateKey.from_private_bytes(raw)
    except ValueError as exc:
        raise RuntimeProofError(
            "runtime private key is invalid"
        ) from exc


def validate_runtime_public_key(value: object) -> str:
    _decode_raw(value, length=32, label="public key")
    return str(value)


def sign_runtime_proof(
    *,
    private_key: Ed25519PrivateKey,
    public_key: str,
    request: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(private_key, Ed25519PrivateKey):
        raise RuntimeProofError("runtime private key is invalid")
    request_payload = _validated_request(request)
    expected_public_key = _encode_raw(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    if public_key != expected_public_key:
        raise RuntimeProofError("runtime public key is invalid")
    unsigned = {
        **request_payload,
        "schema_version": PROOF_SCHEMA,
        "runtime_public_key": public_key,
    }
    signature = private_key.sign(
        _SIGNATURE_DOMAIN + _canonical_bytes(unsigned)
    )
    return {**unsigned, "signature": _encode_raw(signature)}


def verify_runtime_proof(
    *,
    proof: Mapping[str, object],
    expected_request: Mapping[str, object],
    expected_public_key: str,
) -> dict[str, object]:
    payload = dict(proof)
    request = _validated_request(expected_request)
    expected_unsigned = {
        **request,
        "schema_version": PROOF_SCHEMA,
        "runtime_public_key": expected_public_key,
    }
    if (
        set(payload) != _PROOF_KEYS
        or {
            key: payload.get(key)
            for key in expected_unsigned
        }
        != expected_unsigned
    ):
        raise RuntimeProofError("runtime proof binding is invalid")
    public_bytes = _decode_raw(
        expected_public_key,
        length=32,
        label="public key",
    )
    signature = _decode_raw(
        payload.get("signature"),
        length=64,
        label="signature",
    )
    try:
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(
            signature,
            _SIGNATURE_DOMAIN + _canonical_bytes(expected_unsigned),
        )
    except (InvalidSignature, ValueError) as exc:
        raise RuntimeProofError(
            "runtime proof signature is invalid"
        ) from exc
    return payload


__all__ = [
    "PROOF_REQUEST_SCHEMA",
    "PROOF_SCHEMA",
    "RuntimeProofError",
    "decode_runtime_private_key",
    "encode_runtime_private_key",
    "generate_runtime_keypair",
    "runtime_public_key",
    "sign_runtime_proof",
    "validate_runtime_public_key",
    "verify_runtime_proof",
]
