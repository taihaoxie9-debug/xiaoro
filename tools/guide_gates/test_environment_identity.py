"""Build a location-independent identity for a test environment."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any


IDENTITY_SCHEMA = "guide-test-environment-identity-v1"
STABLE_IDENTITY_FIELDS = (
    "artifact_hashes_locked",
    "installed_distribution_count",
    "installed_distributions_sha256",
    "pytest_guide_ini_sha256",
    "python_version",
    "requirements_input_sha256",
)


def stable_environment_identity_sha256(
    manifest: Mapping[str, Any],
) -> str:
    """Hash stable inputs while excluding audit-only filesystem paths."""
    payload = {
        field: manifest[field]
        for field in STABLE_IDENTITY_FIELDS
    }
    payload["schema_version"] = IDENTITY_SCHEMA
    serialized = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()
