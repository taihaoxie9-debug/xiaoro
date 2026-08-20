from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_POSTGRES_PASSWORD = "guide-production-password"


def _compose_environment(
    compose: dict[str, object],
    service_name: str,
) -> dict[str, str]:
    services = compose["services"]
    assert isinstance(services, dict)
    service = services[service_name]
    assert isinstance(service, dict)
    environment = service.get("environment", {})
    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items()}

    assert isinstance(environment, list)
    return {
        key: value
        for item in environment
        for key, value in [str(item).split("=", 1)]
    }


def _effective_production_compose() -> dict[str, object]:
    completed = subprocess.run(
        [
            "docker-compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.prod.yml",
            "config",
        ],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "POSTGRES_PASSWORD": PRODUCTION_POSTGRES_PASSWORD,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    compose = yaml.safe_load(completed.stdout)
    assert isinstance(compose, dict)
    return compose


def test_dockerfile_defaults_to_guide_runtime() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'CMD ["uvicorn", "app.guide_runtime.app:app"' in dockerfile


def test_compose_database_password_matches_all_client_urls() -> None:
    production = _effective_production_compose()
    postgres_password = _compose_environment(
        production,
        "postgres",
    )["POSTGRES_PASSWORD"]
    services = production["services"]
    assert isinstance(services, dict)
    client_passwords = {
        service_name: urlsplit(environment["DATABASE_URL"]).password
        for service_name in services
        for environment in [_compose_environment(production, service_name)]
        if "DATABASE_URL" in environment
    }
    mismatches = {
        service_name: password
        for service_name, password in client_passwords.items()
        if password != postgres_password
    }

    assert postgres_password == PRODUCTION_POSTGRES_PASSWORD
    assert client_passwords
    assert mismatches == {}, (
        "DATABASE_URL passwords must match production POSTGRES_PASSWORD: "
        f"expected {postgres_password!r}, got {mismatches!r}"
    )


def test_guide_runtime_package_imports_without_legacy_modules() -> None:
    supplemental_paths = []
    for module_name in ("PIL", "multipart"):
        module_spec = importlib.util.find_spec(module_name)
        assert module_spec is not None
        assert module_spec.origin is not None
        supplemental_paths.append(
            str(Path(module_spec.origin).resolve().parents[1])
        )
    script = f"""
import sys

sys.path.extend({supplemental_paths!r})
before = set(sys.modules)
import app.guide_runtime.app
loaded = set(sys.modules) - before
forbidden = (
    "app.services",
    "app.database",
    "slowapi",
    "openai",
    "redis",
    "pymilvus",
)
unexpected = sorted(
    name
    for name in loaded
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
)
if unexpected:
    raise RuntimeError(unexpected)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""
