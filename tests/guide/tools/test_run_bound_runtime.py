from __future__ import annotations

from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Callable

import pytest


_HEAD = "a" * 40
_PAYLOAD_SHA256 = "b" * 64
_PLAN_REVISION = "2026-08-23-task11-r5"
_SECRET = "offline-private-key"


def _runner():
    return importlib.import_module(
        "tools.guide_gates.run_bound_runtime"
    )


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_key(path: Path) -> Path:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o600,
    )
    try:
        os.write(descriptor, _SECRET.encode("utf-8"))
    finally:
        os.close(descriptor)
    return path


def _verified_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
    output = tmp_path / "bounded-smoke-attempt-07"
    output.mkdir(parents=True)
    manifest = _write_json(
        tmp_path / "task11-candidate-manifest.json",
        {
            "schema_version": "guide-task11-candidate-manifest-v1",
            "plan_revision": _PLAN_REVISION,
            "candidate_head": _HEAD,
            "protected_payload_sha256": _PAYLOAD_SHA256,
        },
    )
    audit = _write_json(
        tmp_path / "task11-independent-audit.json",
        {
            "schema_version": "guide-task11-independent-audit-v1",
            "passed": True,
            "plan_revision": _PLAN_REVISION,
            "protected_payload_sha256": _PAYLOAD_SHA256,
        },
    )
    readiness = _write_json(
        tmp_path / "task11-candidate-readiness.json",
        {
            "schema_version": "guide-task11-readiness-v1",
            "plan_revision": _PLAN_REVISION,
            "candidate_head": _HEAD,
            "protected_payload_sha256": _PAYLOAD_SHA256,
            "circuit_state": "closed",
            "evidence_files": {
                "candidate_manifest": str(manifest.resolve()),
                "independent_audit": str(audit.resolve()),
            },
            "evidence_sha256": {
                "candidate_manifest": sha256(
                    manifest.read_bytes()
                ).hexdigest(),
                "independent_audit": sha256(
                    audit.read_bytes()
                ).hexdigest(),
            },
        },
    )
    ledger = _write_json(
        tmp_path / "smoke-attempt-ledger.json",
        {
            "schema_version": "guide-smoke-attempt-ledger-v1",
            "revision": 4,
            "circuit_state": "closed",
            "attempts": [
                {
                    "attempt_id": "bounded-smoke-attempt-07",
                    "trajectory_set": "bounded",
                    "result": "allocated",
                    "retry_authorization_id": "auth-07",
                }
            ],
            "authorizations": [
                {
                    "authorization_id": "auth-07",
                    "phase": "bounded",
                    "state": "allocated",
                    "attempt_id": "bounded-smoke-attempt-07",
                }
            ],
        },
    )
    context_payload: dict[str, object] = {
        "schema_version": "guide-smoke-attempt-context-v1",
        "phase_attempt_ids": {
            "bounded": "bounded-smoke-attempt-07",
        },
        "phase_authorization_ids": {"bounded": "auth-07"},
        "output_directory": str(output.resolve()),
        "readiness_path": str(readiness.resolve()),
        "readiness_sha256": sha256(readiness.read_bytes()).hexdigest(),
        "ledger_path": str(ledger.resolve()),
        "allocated_ledger_revision": 4,
    }
    context = _write_json(
        output / "attempt-context.json",
        context_payload,
    )
    readiness_payload = json.loads(
        readiness.read_text(encoding="utf-8")
    )
    return context, ledger, context_payload, readiness_payload


def _install_verified_apis(
    monkeypatch: pytest.MonkeyPatch,
    runner,
    *,
    context: dict[str, object],
    readiness: dict[str, object],
    ledger_path: Path,
) -> list[str]:
    calls: list[str] = []

    def read_context(
        path: str | Path,
        *,
        ledger_path: str | Path,
        readiness_path: str | Path,
    ) -> dict[str, object]:
        del path, ledger_path, readiness_path
        calls.append("context")
        return context

    def verify_readiness(
        *,
        readiness_path: str | Path,
        ledger_path: str | Path,
    ) -> dict[str, object]:
        del readiness_path, ledger_path
        calls.append("readiness")
        return readiness

    monkeypatch.setattr(runner, "read_attempt_context", read_context)
    monkeypatch.setattr(
        runner,
        "verify_task11_readiness",
        verify_readiness,
    )
    monkeypatch.setattr(
        runner,
        "read_ledger",
        lambda path: (
            calls.append("ledger")
            or json.loads(Path(path).read_text(encoding="utf-8"))
        ),
    )
    assert Path(str(context["ledger_path"])) == ledger_path.resolve()
    return calls


class _Server:
    def __init__(
        self,
        *,
        assertion: Callable[[], None] | None = None,
        fail: bool = False,
    ) -> None:
        self.started = False
        self.assertion = assertion
        self.fail = fail

    async def serve(self) -> None:
        if self.fail:
            raise RuntimeError("offline startup failure")
        if self.assertion is not None:
            self.assertion()
        self.started = True


def test_import_does_not_load_application_or_start_runtime() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys;"
                "import tools.guide_gates.run_bound_runtime;"
                "assert 'app.guide_runtime.app' not in sys.modules"
            ),
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_runtime_verifies_all_authority_before_loading_application(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    calls = _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    key_path = _write_key(tmp_path / "api-key")
    state_dir = tmp_path / "state"
    observed_environment: dict[str, str | None] = {}

    def load_application() -> object:
        calls.append("application")
        for name in runner.BOUND_PROVIDER_ENVIRONMENT:
            observed_environment[name] = os.environ.get(name)
        return object()

    identity = runner.run_bound_runtime(
        attempt_context=context_path,
        host="127.0.0.1",
        port=8821,
        state_dir=state_dir,
        key_path=key_path,
        application_loader=load_application,
        server_factory=lambda application, host, port: _Server(
            assertion=lambda: calls.append("server")
        ),
    )

    assert calls == [
        "context",
        "readiness",
        "ledger",
        "application",
        "server",
    ]
    assert observed_environment == {
        "GUIDE_LLM_API_KEY": _SECRET,
        "GUIDE_LLM_BASE_URL": "https://api.deepseek.com",
        "GUIDE_LLM_MODEL": "deepseek-v4-pro",
        "GUIDE_LLM_TIMEOUT_SECONDS": "30",
        "GUIDE_LLM_MAX_TOKENS": "1024",
        "GUIDE_LLM_DAILY_BUDGET_CNY": "3.00",
        "GUIDE_LLM_DAILY_CALL_CAP": "9",
        "GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS": "0",
        "GUIDE_COPY_LLM_API_KEY": _SECRET,
        "GUIDE_COPY_LLM_BASE_URL": "https://api.deepseek.com",
        "GUIDE_COPY_LLM_MODEL": "deepseek-v4-pro",
        "GUIDE_COPY_LLM_TIMEOUT_SECONDS": "30",
        "GUIDE_COPY_LLM_MAX_TOKENS": "1536",
        "GUIDE_COPY_LLM_TEMPERATURE": "0.3",
        "GUIDE_COPY_LLM_DAILY_BUDGET_CNY": "3.00",
        "GUIDE_COPY_LLM_DAILY_CALL_CAP": "9",
    }
    assert identity["schema_version"] == (
        "guide-bound-runtime-identity-v1"
    )
    assert identity["phase"] == "bounded"
    assert identity["attempt_id"] == "bounded-smoke-attempt-07"
    assert identity["readiness_sha256"] == sha256(
        Path(str(context["readiness_path"])).read_bytes()
    ).hexdigest()
    assert identity["candidate_manifest_sha256"] == (
        readiness["evidence_sha256"]["candidate_manifest"]
    )
    assert identity["independent_audit_sha256"] == (
        readiness["evidence_sha256"]["independent_audit"]
    )
    assert identity["provider_limits"] == {
        "copywriter": {
            "daily_budget_cny": "3.00",
            "daily_call_cap": 9,
            "max_tokens": 1536,
            "timeout_seconds": 30,
        },
        "turn_meaning": {
            "daily_budget_cny": "3.00",
            "daily_call_cap": 9,
            "format_repair_attempts": 0,
            "max_tokens": 1024,
            "timeout_seconds": 30,
        },
    }
    identity_path = Path(str(context["output_directory"])) / (
        "runtime-identity.json"
    )
    assert json.loads(identity_path.read_text(encoding="utf-8")) == identity
    assert stat.S_IMODE(identity_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert _SECRET not in identity_path.read_text(encoding="utf-8")


def test_plan_environment_is_accepted_but_limits_are_not_overridable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    environment = {
        "GUIDE_LLM_API_KEY": _SECRET,
        "GUIDE_COPY_LLM_API_KEY": _SECRET,
        "GUIDE_LLM_BASE_URL": "https://api.deepseek.com",
        "GUIDE_LLM_MODEL": "deepseek-v4-pro",
        "GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS": "0",
        "GUIDE_COPY_LLM_BASE_URL": "https://api.deepseek.com",
        "GUIDE_COPY_LLM_MODEL": "deepseek-v4-pro",
    }

    runner.run_bound_runtime(
        attempt_context=context_path,
        host="127.0.0.1",
        port=8821,
        state_dir=tmp_path / "state",
        environ=environment,
        application_loader=object,
        server_factory=lambda application, host, port: _Server(),
    )

    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path / "second"
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    environment["GUIDE_LLM_DAILY_CALL_CAP"] = "10"
    with pytest.raises(
        runner.BoundRuntimeError,
        match="fixed provider setting",
    ):
        runner.run_bound_runtime(
            attempt_context=context_path,
            host="127.0.0.1",
            port=8821,
            state_dir=tmp_path / "second-state",
            environ=environment,
            application_loader=lambda: pytest.fail(
                "application must not load"
            ),
            server_factory=lambda application, host, port: pytest.fail(
                "server must not start"
            ),
        )


def test_invalid_readiness_fails_before_key_or_application(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    calls = _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )

    def reject_readiness(**kwargs):
        del kwargs
        calls.append("readiness-rejected")
        raise ValueError("readiness rejected")

    monkeypatch.setattr(
        runner,
        "verify_task11_readiness",
        reject_readiness,
    )
    monkeypatch.setattr(
        runner,
        "read_private_api_key",
        lambda path: pytest.fail("key must not be read"),
    )

    with pytest.raises(ValueError, match="readiness rejected"):
        runner.run_bound_runtime(
            attempt_context=context_path,
            host="127.0.0.1",
            port=8821,
            state_dir=tmp_path / "state",
            key_path=tmp_path / "missing-key",
            application_loader=lambda: pytest.fail(
                "application must not load"
            ),
            server_factory=lambda application, host, port: pytest.fail(
                "server must not start"
            ),
        )

    assert calls == ["context", "readiness-rejected"]
    assert not (tmp_path / "state").exists()


def test_independent_audit_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    audit = Path(
        str(readiness["evidence_files"]["independent_audit"])
    )
    audit.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        runner.BoundRuntimeError,
        match="independent audit",
    ):
        runner.run_bound_runtime(
            attempt_context=context_path,
            host="127.0.0.1",
            port=8821,
            state_dir=tmp_path / "state",
            key_path=tmp_path / "missing-key",
            application_loader=lambda: pytest.fail(
                "application must not load"
            ),
            server_factory=lambda application, host, port: pytest.fail(
                "server must not start"
            ),
        )


@pytest.mark.parametrize(
    ("attempt_result", "authorization_state"),
    [("consumed", "allocated"), ("allocated", "consumed")],
)
def test_runtime_rejects_nonfresh_attempt_without_consuming_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    attempt_result: str,
    authorization_state: str,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["attempts"][0]["result"] = attempt_result
    ledger["authorizations"][0]["state"] = authorization_state
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    before = ledger_path.read_bytes()

    with pytest.raises(
        runner.BoundRuntimeError,
        match="fresh allocated attempt",
    ):
        runner.run_bound_runtime(
            attempt_context=context_path,
            host="127.0.0.1",
            port=8821,
            state_dir=tmp_path / "state",
            key_path=tmp_path / "missing-key",
            application_loader=lambda: pytest.fail(
                "application must not load"
            ),
            server_factory=lambda application, host, port: pytest.fail(
                "server must not start"
            ),
        )
    assert ledger_path.read_bytes() == before


def test_runtime_rejects_non_loopback_before_authority_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    monkeypatch.setattr(
        runner,
        "read_attempt_context",
        lambda *args, **kwargs: pytest.fail(
            "authority must not be read for unsafe bind"
        ),
    )

    with pytest.raises(runner.BoundRuntimeError, match="loopback"):
        runner.run_bound_runtime(
            attempt_context=tmp_path / "missing-context",
            host="0.0.0.0",
            port=8821,
            state_dir=tmp_path / "state",
        )


def test_server_startup_failure_writes_no_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    key_path = _write_key(tmp_path / "api-key")

    with pytest.raises(RuntimeError, match="offline startup failure"):
        runner.run_bound_runtime(
            attempt_context=context_path,
            host="127.0.0.1",
            port=8821,
            state_dir=tmp_path / "state",
            key_path=key_path,
            application_loader=object,
            server_factory=lambda application, host, port: _Server(
                fail=True
            ),
        )

    assert not (
        Path(str(context["output_directory"]))
        / "runtime-identity.json"
    ).exists()


def test_cli_surface_matches_the_task11_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    observed: dict[str, object] = {}

    def fake_run(**kwargs):
        observed.update(kwargs)
        return {"passed": True}

    monkeypatch.setattr(runner, "run_bound_runtime", fake_run)

    assert runner.main(
        [
            "--attempt-context",
            str(tmp_path / "attempt-context.json"),
            "--host",
            "127.0.0.1",
            "--port",
            "8821",
            "--state-dir",
            str(tmp_path / "state"),
        ]
    ) == 0
    assert observed["attempt_context"] == (
        tmp_path / "attempt-context.json"
    )
    assert observed["host"] == "127.0.0.1"
    assert observed["port"] == 8821
    assert observed["state_dir"] == tmp_path / "state"
