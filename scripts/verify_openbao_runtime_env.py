from __future__ import annotations

import sys
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_SENSITIVE_RUNTIME_KEYS = (
    "DJANGO_SECRET_KEY",
    "ALE_MASTER_KEY",
    "ALE_SEARCH_SECRET",
    "ALE_KDF_SALT",
    "POSTGRES_PASSWORD",
    "POSTGRES_ADMIN_PASSWORD",
    "RABBITMQ_PASSWORD",
    "MINIO_ROOT_PASSWORD",
    "STORAGE_SECRET_KEY",
    "SIGNOZ_PASSWORD",
    "SIGNOZ_BOOTSTRAP_PASSWORD",
    "SIGNOZ_EMAILING_AUTH_PASSWORD",
    "CELERY_BROKER_URL",
)


def _truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_nonexpiring_ttl(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"0", "0s", "0m", "0h", "0d", "0w"}


def _collect_openbao_addrs(values: dict[str, str | None]) -> list[str]:
    raw_addrs = str(values.get("BAO_ADDRS", "")).strip()
    if raw_addrs:
        return [item.strip().rstrip("/") for item in raw_addrs.split(",") if item.strip()]
    single = str(values.get("BAO_ADDR", "")).strip()
    if single:
        return [single.rstrip("/")]
    return []


def _looks_like_windows_path(value: str) -> bool:
    cleaned = value.strip()
    if len(cleaned) < 3:
        return False
    return cleaned[1:3] in {":\\", ":/"}


def _env_path() -> Path:
    from core.env_files import resolve_env_file

    repo_root = Path(__file__).resolve().parents[1]
    base_dir = repo_root / "server"
    return resolve_env_file(repo_root, base_dir)


def main() -> None:
    env_path = _env_path()
    if not env_path.exists():
        raise SystemExit(f"verify_openbao_runtime_env: missing env file: {env_path}")

    values = dotenv_values(env_path)
    backend = str(values.get("IMMOAPP_SECRETS_BACKEND", "openbao")).strip().lower()
    allow_env = _truthy(str(values.get("IMMOAPP_ALLOW_ENV_SECRETS", "0")))
    allow_plain_token = _truthy(str(values.get("IMMOAPP_ALLOW_PLAINTEXT_BAO_TOKEN", "0")))
    bao_verify_ssl = _truthy(str(values.get("BAO_VERIFY_SSL", "1")))
    openbao_addrs = _collect_openbao_addrs(values)

    if backend != "openbao" or allow_env:
        print(
            "verify_openbao_runtime_env: skipped "
            f"(backend={backend}, allow_env_secrets={allow_env})"
        )
        return

    env_mode = str(values.get("IMMOAPP_ENV", "")).strip().lower()
    debug_val = str(values.get("DJANGO_DEBUG", "")).strip()
    production_mode = False
    if env_mode in {"prod", "production"}:
        production_mode = True
    elif env_mode in {"dev", "development", "local", "test", "ci"}:
        production_mode = False
    elif debug_val:
        production_mode = not _truthy(debug_val)
    else:
        production_mode = True

    if bao_verify_ssl:
        non_https = [addr for addr in openbao_addrs if not addr.lower().startswith("https://")]
        if non_https:
            raise SystemExit(
                "verify_openbao_runtime_env: BAO_VERIFY_SSL=1 requires https:// OpenBao addresses. "
                f"Found non-HTTPS endpoint(s): {', '.join(non_https)}. "
                "Use BAO_VERIFY_SSL=0 for http:// in local dev, or switch OpenBao to TLS."
            )

    violations: list[str] = []
    for key in _SENSITIVE_RUNTIME_KEYS:
        value = values.get(key)
        if value is None:
            continue
        if str(value).strip():
            violations.append(key)

    if violations:
        raise SystemExit(
            "verify_openbao_runtime_env: runtime env must not store app secrets in OpenBao-only mode: "
            + ", ".join(violations)
            + f" (file: {env_path})"
        )

    if not allow_plain_token:
        plain_token = str(values.get("BAO_TOKEN", "")).strip()
        if plain_token:
            raise SystemExit(
                "verify_openbao_runtime_env: BAO_TOKEN must not be set directly when "
                "OpenBao-only policy is active. Use BAO_TOKEN_FILE or AppRole credentials."
            )

    # Container overrides must never use host-native Windows paths.
    docker_approle = str(values.get("BAO_APPROLE_FILE_DOCKER", "")).strip()
    docker_token_file = str(values.get("BAO_TOKEN_FILE_DOCKER", "")).strip()
    docker_bootstrap_token_file = str(values.get("BAO_BOOTSTRAP_TOKEN_FILE_DOCKER", "")).strip()
    docker_unseal_key_file = str(values.get("BAO_UNSEAL_KEY_FILE_DOCKER", "")).strip()
    if docker_approle and _looks_like_windows_path(docker_approle):
        raise SystemExit(
            "verify_openbao_runtime_env: BAO_APPROLE_FILE_DOCKER must be a container path "
            f"(got Windows path: {docker_approle})."
        )
    if docker_token_file and _looks_like_windows_path(docker_token_file):
        raise SystemExit(
            "verify_openbao_runtime_env: BAO_TOKEN_FILE_DOCKER must be a container path "
            f"(got Windows path: {docker_token_file})."
        )
    if docker_bootstrap_token_file and _looks_like_windows_path(docker_bootstrap_token_file):
        raise SystemExit(
            "verify_openbao_runtime_env: BAO_BOOTSTRAP_TOKEN_FILE_DOCKER must be a container path "
            f"(got Windows path: {docker_bootstrap_token_file})."
        )
    if docker_unseal_key_file and _looks_like_windows_path(docker_unseal_key_file):
        raise SystemExit(
            "verify_openbao_runtime_env: BAO_UNSEAL_KEY_FILE_DOCKER must be a container path "
            f"(got Windows path: {docker_unseal_key_file})."
        )

    if production_mode and not allow_plain_token:
        token_file = str(values.get("BAO_TOKEN_FILE", "")).strip()
        approle_file = str(values.get("BAO_APPROLE_FILE", "")).strip()
        role_id = str(values.get("BAO_ROLE_ID", "")).strip()
        secret_id = str(values.get("BAO_SECRET_ID", "")).strip()
        if not token_file and not approle_file and not (role_id and secret_id):
            raise SystemExit(
                "verify_openbao_runtime_env: missing OpenBao auth for production "
                "(require BAO_TOKEN_FILE, BAO_APPROLE_FILE, or BAO_ROLE_ID+BAO_SECRET_ID)."
            )
        if token_file and not Path(token_file).expanduser().exists():
            raise SystemExit(
                "verify_openbao_runtime_env: BAO_TOKEN_FILE is configured but missing on disk: "
                + token_file
            )
        if approle_file and not Path(approle_file).expanduser().exists():
            raise SystemExit(
                "verify_openbao_runtime_env: BAO_APPROLE_FILE is configured but missing on disk: "
                + approle_file
            )
        secret_id_ttl = str(values.get("OPENBAO_APPROLE_SECRET_ID_TTL", "")).strip()
        if secret_id_ttl and _is_nonexpiring_ttl(secret_id_ttl):
            raise SystemExit(
                "verify_openbao_runtime_env: OPENBAO_APPROLE_SECRET_ID_TTL must be finite in production "
                f"(got '{secret_id_ttl}')."
            )

    print("verify_openbao_runtime_env: OK")


if __name__ == "__main__":
    main()
