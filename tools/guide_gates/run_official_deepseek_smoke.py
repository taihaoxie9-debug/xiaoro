"""Real execution entry point for the official DeepSeek intent A/B runner.

This module is the supervised injection wrapper for
``run_real_deepseek_intent_ab``. That runner returns a typed BLOCKED result
(exit 4) until real execution dependencies are injected. This entry point:

* reads the current DeepSeek API key from a private ``0600`` regular file with
  strict, symlink-resistant prechecks;
* assembles the real official adapters and evaluator;
* injects them into the frozen 32-case smoke / conditional 128-case gate.

The API key is never placed in argv, logs, exceptions, reports, evidence, or
Git. It only travels through function arguments into the runner, which forwards
it to the official adapters and scrubs it from every evidence payload.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import Enum
import errno
import json
import os
from pathlib import Path
import stat
import sys

from app.guide.adapters.llm.deepseek_intent import DeepSeekIntentAdapter
from app.guide.adapters.llm.deepseek_two_stage_intent import (
    DeepSeekTwoStageIntentAdapter,
)
from app.guide_runtime.llm_config import GuideLlmConfig
from tools.guide_gates.guide_pipeline_evaluator import (
    ModelVerticalEvaluator,
)
from tools.guide_gates import run_real_deepseek_intent_ab as deepseek_runner


DEFAULT_KEY_PATH = "/private/tmp/xiaoro-deepseek-api-key"
_MAX_KEY_BYTES = 1024
_EXPECTED_KEY_MODE = 0o600
_EXIT_KEY_PRECHECK_FAILED = 5

RunnerMain = Callable[..., int]


class KeyPrecheckCode(str, Enum):
    UNAVAILABLE = "key_unavailable"
    SYMLINK = "key_is_symlink"
    NOT_REGULAR = "key_not_regular_file"
    MODE = "key_mode_not_0600"
    SIZE = "key_size_out_of_range"
    ENCODING = "key_not_utf8"
    WHITESPACE = "key_has_edge_whitespace"
    CONTROL = "key_has_control_character"


class KeyPrecheckError(Exception):
    """Raised when the private key file fails a precheck.

    The message is intentionally the typed code only. The key value is never
    included so raising, logging, or printing this error cannot leak it.
    """

    def __init__(self, code: KeyPrecheckCode) -> None:
        self.code = code
        super().__init__(code.value)


def read_private_api_key(path: str | Path) -> str:
    """Return the API key from a private ``0600`` regular file.

    Prechecks: reject symlinks, non-regular files, mode other than ``0600``,
    size outside ``1..1024`` bytes, non-UTF-8 content, leading/trailing
    whitespace, and control characters. The file is opened with ``O_NOFOLLOW``
    and re-validated through the descriptor to resist symlink races.
    """
    key_path = Path(path)
    try:
        link_status = os.lstat(key_path)
    except OSError as exc:
        raise KeyPrecheckError(KeyPrecheckCode.UNAVAILABLE) from exc
    _validate_status(link_status)

    try:
        descriptor = os.open(
            key_path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as exc:
        code = (
            KeyPrecheckCode.SYMLINK
            if getattr(exc, "errno", None) == errno.ELOOP
            else KeyPrecheckCode.UNAVAILABLE
        )
        raise KeyPrecheckError(code) from exc

    try:
        _validate_status(os.fstat(descriptor))
        raw = os.read(descriptor, _MAX_KEY_BYTES + 1)
    finally:
        os.close(descriptor)

    if not raw or len(raw) > _MAX_KEY_BYTES:
        raise KeyPrecheckError(KeyPrecheckCode.SIZE)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KeyPrecheckError(KeyPrecheckCode.ENCODING) from exc
    if text != text.strip():
        raise KeyPrecheckError(KeyPrecheckCode.WHITESPACE)
    if not text:
        raise KeyPrecheckError(KeyPrecheckCode.SIZE)
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise KeyPrecheckError(KeyPrecheckCode.CONTROL)
    return text


def _validate_status(status: os.stat_result) -> None:
    if stat.S_ISLNK(status.st_mode):
        raise KeyPrecheckError(KeyPrecheckCode.SYMLINK)
    if not stat.S_ISREG(status.st_mode):
        raise KeyPrecheckError(KeyPrecheckCode.NOT_REGULAR)
    if stat.S_IMODE(status.st_mode) != _EXPECTED_KEY_MODE:
        raise KeyPrecheckError(KeyPrecheckCode.MODE)
    if not 1 <= status.st_size <= _MAX_KEY_BYTES:
        raise KeyPrecheckError(KeyPrecheckCode.SIZE)


def build_two_stage_adapter(
    config: GuideLlmConfig,
) -> DeepSeekTwoStageIntentAdapter:
    """Build the official two-stage adapter (V4-Flash / V4-Pro lanes)."""
    ready = config.require_ready()
    api_key = ready.api_key
    model = ready.model
    if api_key is None or model is None:
        raise AssertionError("ready Guide LLM configuration is incomplete")
    return DeepSeekTwoStageIntentAdapter(
        api_key=api_key,
        model=model,
        timeout_seconds=ready.timeout_seconds,
        base_url=ready.base_url,
        max_tokens=ready.max_tokens,
        format_repair_attempts=ready.format_repair_attempts,
        daily_budget_cny=ready.daily_budget_cny,
        daily_call_cap=ready.daily_call_cap,
    )


def build_single_stage_adapter(
    config: GuideLlmConfig,
) -> DeepSeekIntentAdapter:
    """Build the V4-Pro single-stage non-production control adapter."""
    ready = config.require_ready()
    api_key = ready.api_key
    model = ready.model
    if api_key is None or model is None:
        raise AssertionError("ready Guide LLM configuration is incomplete")
    return DeepSeekIntentAdapter(
        api_key=api_key,
        model=model,
        timeout_seconds=ready.timeout_seconds,
        base_url=ready.base_url,
        max_tokens=ready.max_tokens,
        format_repair_attempts=ready.format_repair_attempts,
        daily_budget_cny=ready.daily_budget_cny,
        daily_call_cap=ready.daily_call_cap,
    )


def evaluator_factory() -> ModelVerticalEvaluator:
    """Build the real text-vertical pipeline evaluator."""
    return ModelVerticalEvaluator()


def _emit_precheck_failure(code: KeyPrecheckCode) -> None:
    print(
        json.dumps(
            {"code": code.value, "status": "key_precheck_failed"},
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    key_path: str | Path = DEFAULT_KEY_PATH,
    runner_main: RunnerMain = deepseek_runner.main,
) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    try:
        api_key = read_private_api_key(key_path)
    except KeyPrecheckError as failure:
        _emit_precheck_failure(failure.code)
        return _EXIT_KEY_PRECHECK_FAILED
    return runner_main(
        arguments,
        config=deepseek_runner.DeepSeekRunnerConfig(),
        api_key=api_key,
        two_stage_adapter_factory=build_two_stage_adapter,
        single_stage_adapter_factory=build_single_stage_adapter,
        evaluator_factory=evaluator_factory,
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_KEY_PATH",
    "KeyPrecheckCode",
    "KeyPrecheckError",
    "build_single_stage_adapter",
    "build_two_stage_adapter",
    "evaluator_factory",
    "main",
    "read_private_api_key",
]
