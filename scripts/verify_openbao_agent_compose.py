from __future__ import annotations

from pathlib import Path

from repo_layout import COMPOSE_YML


def _require_tokens(path: Path, tokens: tuple[str, ...]) -> None:
    text = path.read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            raise AssertionError(f"{path}: missing token: {token}")


def _forbid_tokens(path: Path, tokens: tuple[str, ...]) -> None:
    text = path.read_text(encoding="utf-8")
    for token in tokens:
        if token in text:
            raise AssertionError(f"{path}: forbidden legacy token found: {token}")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    compose_path = COMPOSE_YML
    if not compose_path.exists():
        raise AssertionError("deployment/compose/compose.yml not found.")
    legacy_compose = repo_root / "compose.secrets.yml"
    if legacy_compose.exists():
        raise AssertionError("compose.secrets.yml must not exist in single-stack OpenBao mode.")

    _require_tokens(
        compose_path,
        (
            "openbao:",
            "command: server -config=/openbao/config/openbao.hcl",
            "openbao-init:",
            "openbao-seed:",
            "BAO_APPROLE_FILE: ${BAO_APPROLE_FILE_DOCKER:-/run/immoapp-secrets/openbao-approle.json}",
            "BAO_TOKEN_FILE: ${BAO_TOKEN_FILE_DOCKER:-}",
            "openbao-init:\n        condition: service_completed_successfully",
            "openbao-seed:\n        condition: service_completed_successfully",
            'command: ["python", "-m", "server.secret_store.openbao_runtime_init"]',
            'command: ["python", "-m", "server.secret_store.openbao_runtime_seed"]',
            "server.secret_store.openbao_runtime_bootstrap",
        ),
    )

    _forbid_tokens(
        compose_path,
        (
            "openbao-agent:",
            "openbao-approle-init:",
            "openbao-agent-init:",
            "/openbao/token/token",
        ),
    )

    _require_tokens(
        repo_root / "server" / "secret_store" / "openbao_runtime_init.py",
        (
            "def _initialize_openbao(",
            "def _unseal_openbao(",
            "def _validate_admin_token(",
        ),
    )

    _require_tokens(
        repo_root / "server" / "secret_store" / "openbao_runtime_guard.py",
        (
            "def _resolve_token(",
            "def _validate_required(",
        ),
    )

    _require_tokens(
        repo_root / "server" / "secret_store" / "openbao_runtime_bootstrap.py",
        (
            "def _is_retryable(",
            "IMMOAPP_BAO_BOOTSTRAP_MAX_ATTEMPTS",
            "IMMOAPP_BAO_BOOTSTRAP_RETRY_SECONDS",
            "guard_main()",
        ),
    )

    _require_tokens(
        repo_root / "server" / "secret_store" / "openbao_runtime_seed.py",
        (
            "def _ensure_auth_mounts(",
            "def _ensure_approle(",
            "def _write_and_verify_secret(",
        ),
    )

    print("verify_openbao_agent_compose: OK (persistent single-stack OpenBao mode)")


if __name__ == "__main__":
    main()
