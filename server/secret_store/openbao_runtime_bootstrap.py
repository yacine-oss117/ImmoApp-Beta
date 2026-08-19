from __future__ import annotations

import os
import sys
import time

from .openbao_runtime_guard import RuntimeGuardError
from .openbao_runtime_guard import main as guard_main

__all__ = ("main",)

_RETRYABLE_PREFIXES: tuple[str, ...] = (
    "OpenBao connection failure",
    "OpenBao HTTP 5",
)

_RETRYABLE_MARKERS: tuple[str, ...] = ("Vault is sealed",)

_FATAL_MARKERS: tuple[str, ...] = (
    "No OpenBao auth configured",
    "BAO_TOKEN_FILE not found",
    "BAO_TOKEN_FILE is empty",
    "BAO_TOKEN_FILE must be container path",
    "BAO_APPROLE_FILE not found",
    "BAO_APPROLE_FILE is missing app_role_id/app_secret_id",
    "BAO_APPROLE_FILE must be container path",
    "BAO_ADDR is empty",
    "IMMOAPP_SECRETS_PATH is empty",
    "OpenBao secret path not found",
    "OpenBao secret path is present but missing required keys",
    "AppRole login returned no client token.",
)


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, str(default))).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, 1)


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name, str(default))).strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(value, 0.1)


def _is_retryable(exc: RuntimeGuardError) -> bool:
    message = str(exc)
    if any(marker in message for marker in _FATAL_MARKERS):
        return False
    if any(message.startswith(prefix) for prefix in _RETRYABLE_PREFIXES):
        return True
    if any(marker in message for marker in _RETRYABLE_MARKERS):
        return True
    return False


def main() -> None:
    max_attempts = _env_int("IMMOAPP_BAO_BOOTSTRAP_MAX_ATTEMPTS", 20)
    sleep_seconds = _env_float("IMMOAPP_BAO_BOOTSTRAP_RETRY_SECONDS", 2.0)
    attempt = 1
    while True:
        try:
            guard_main()
            return
        except RuntimeGuardError as exc:
            if attempt >= max_attempts or not _is_retryable(exc):
                print(
                    "openbao_runtime_bootstrap: ERROR: "
                    f"failed after {attempt} attempt(s): {exc}",
                    file=sys.stderr,
                )
                raise SystemExit(1) from exc
            print(
                "openbao_runtime_bootstrap: waiting for OpenBao readiness "
                f"(attempt {attempt}/{max_attempts}): {exc}",
                file=sys.stderr,
            )
            attempt += 1
            time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
