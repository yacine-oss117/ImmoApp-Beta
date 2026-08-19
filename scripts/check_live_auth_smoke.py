from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_HOST_OVERRIDE_KEYS = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "PGCONNECT_TIMEOUT",
    "VALKEY_URL",
    "CHANNEL_LAYER_URL",
    "STORAGE_ENDPOINT_URL",
    "STORAGE_USE_SSL",
    "STORAGE_CLAMD_HOST",
    "BAO_ADDR",
    "CELERY_BROKER_URL",
)

_BOOTSTRAP_SECRET_KEYS = (
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_ADMIN_USER",
    "POSTGRES_ADMIN_PASSWORD",
    "ALE_KEY_VERSION",
    "ALE_MASTER_KEY",
    "ALE_SEARCH_SECRET",
    "ALE_KDF_SALT",
    "RABBITMQ_PASSWORD",
    "MINIO_ROOT_PASSWORD",
    "STORAGE_SECRET_KEY",
    "CELERY_BROKER_URL",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live auth smoke: server + login + main window init."
    )
    parser.add_argument(
        "--server-python", default=os.environ.get("IMMOAPP_SERVER_PYTHON", "python")
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--startup-timeout-sec", type=float, default=45.0)
    parser.add_argument("--request-timeout-sec", type=float, default=8.0)
    parser.add_argument("--seed", action="store_true", default=True)
    parser.add_argument("--no-seed", dest="seed", action="store_false")
    return parser.parse_args()


def _bootstrap_secret_file(env: dict[str, str]) -> Path:
    explicit = str(env.get("IMMOAPP_BOOTSTRAP_SECRETS_FILE", "")).strip()
    if explicit:
        return Path(explicit)
    appdata_root = str(env.get("IMMOAPP_APPDATA_ROOT", "")).strip()
    if not appdata_root and os.name == "nt":
        program_data = str(env.get("PROGRAMDATA", "")).strip()
        if program_data:
            appdata_root = str(Path(program_data) / "ImmoApp")
    return Path(appdata_root) / "secrets" / "immoapp-dev-secrets.json"


def _load_bootstrap_secret_env(env: dict[str, str]) -> None:
    secrets_path = _bootstrap_secret_file(env)
    if not secrets_path.exists():
        return
    try:
        payload = json.loads(secrets_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(payload, dict):
        return

    for key in _BOOTSTRAP_SECRET_KEYS:
        if str(env.get(key, "")).strip():
            continue
        value = payload.get(key)
        if value is not None and str(value).strip():
            env[key] = str(value)


def _url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _normalize_host_runtime_env(env: dict[str, str]) -> None:
    postgres_host = str(env.get("POSTGRES_HOST", "")).strip()
    if not postgres_host or postgres_host == "db":
        env["POSTGRES_HOST"] = "127.0.0.1"
    env.setdefault("POSTGRES_PORT", "5432")
    env.setdefault("PGCONNECT_TIMEOUT", "5")

    bao_addr = str(env.get("BAO_ADDR", "")).strip()
    if not bao_addr or "://openbao" in bao_addr:
        env["BAO_ADDR"] = "http://127.0.0.1:8200"

    valkey_url = str(env.get("VALKEY_URL", "")).strip()
    if not valkey_url or valkey_url.startswith("redis://valkey"):
        env["VALKEY_URL"] = "redis://127.0.0.1:6379/1"

    channel_layer_url = str(env.get("CHANNEL_LAYER_URL", "")).strip()
    if not channel_layer_url or channel_layer_url.startswith("redis://valkey"):
        env["CHANNEL_LAYER_URL"] = "redis://127.0.0.1:6379/3"

    storage_endpoint = str(env.get("STORAGE_ENDPOINT_URL", "")).strip()
    if not storage_endpoint or "://minio" in storage_endpoint:
        env["STORAGE_ENDPOINT_URL"] = "http://127.0.0.1:9000"
    env.setdefault("STORAGE_USE_SSL", "0")

    storage_clamd_host = str(env.get("STORAGE_CLAMD_HOST", "")).strip()
    if not storage_clamd_host or storage_clamd_host == "clamav":
        env["STORAGE_CLAMD_HOST"] = "127.0.0.1"

    broker_url = str(env.get("CELERY_BROKER_URL", "")).strip()
    if "@rabbitmq" in broker_url:
        env["CELERY_BROKER_URL"] = broker_url.replace("@rabbitmq", "@127.0.0.1")


def _configure_isolated_smoke_secrets(env: dict[str, str]) -> None:
    """Keep the local auth smoke independent from production secret services."""
    env["IMMOAPP_SECRETS_BACKEND"] = "env"
    env["IMMOAPP_ALLOW_ENV_SECRETS"] = "1"
    env["IMMOAPP_SECRETS_REQUIRED"] = "0"
    env["IMMOAPP_SECRETS_OVERWRITE"] = "0"
    env["IMMOAPP_ENV"] = "ci"
    env["IMMOAPP_SKIP_CELERY_APP"] = "1"
    env["IMMOAPP_ALLOW_HTTP_ONLY_ASGI_FALLBACK"] = "1"
    env["DJANGO_SECRET_KEY"] = "live-auth-smoke-secret-key-unsafe-for-production"
    env["DJANGO_DEBUG"] = "1"
    env["DJANGO_ALLOWED_HOSTS"] = "localhost,127.0.0.1"


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout_sec: float = 8.0,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    body: bytes | None = None
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            if not isinstance(parsed, dict):
                return int(response.status), {}
            return int(response.status), parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except Exception:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        return int(exc.code), parsed


def _wait_for_server(base_url: str, timeout_sec: float, request_timeout_sec: float) -> None:
    deadline = time.time() + timeout_sec
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            status, _ = _http_json(
                "GET",
                _url(base_url, "/api/v1/health/"),
                timeout_sec=request_timeout_sec,
            )
            if status == 200:
                return
        except Exception as exc:  # pragma: no cover - diagnostic only
            last_error = exc
        time.sleep(1.0)
    raise RuntimeError(
        f"Server did not become healthy within {timeout_sec}s. Last error: {last_error}"
    )


def _seed_admin(server_python: str, env: dict[str, str], root: Path) -> None:
    seed_script = root / "scripts" / "seed_initial.py"
    cmd = [server_python, str(seed_script)]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=45,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Seeding timed out after 45s.") from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"Seeding failed ({result.returncode}). stdout={result.stdout[-800:]} stderr={result.stderr[-800:]}"
        )


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _tail(path: Path, max_chars: int = 3000) -> str:
    if not path.exists():
        return ""
    data = path.read_text(encoding="utf-8", errors="replace")
    return data[-max_chars:]


def _assert_api_login(
    base_url: str, username: str, password: str, request_timeout_sec: float
) -> str:
    status, payload = _http_json(
        "POST",
        _url(base_url, "/api/auth/token/"),
        payload={"username": username, "password": password},
        timeout_sec=request_timeout_sec,
    )
    if status != 200:
        raise RuntimeError(f"Auth failed: status={status}, payload={payload}")
    token = payload.get("access")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"Auth response missing access token: payload={payload}")
    return token


def _assert_client_login_and_main_window(base_url: str, username: str, password: str) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("IMMOAPP_STARTUP_LIGHT", "1")
    os.environ["IMMOAPP_API_BASE_URL"] = base_url

    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    from app.main_window import MainWindow
    from app.widgets import login_dialog as login_dialog_module
    from app.widgets.login_dialog import LoginDialog

    app = QApplication.instance() or QApplication([])

    original_warning = QMessageBox.warning
    original_information = QMessageBox.information
    original_critical = QMessageBox.critical
    original_flush = login_dialog_module.flush_pending_media_uploads

    def _no_modal(*_args, **_kwargs) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Ok

    QMessageBox.warning = _no_modal  # type: ignore[assignment]
    QMessageBox.information = _no_modal  # type: ignore[assignment]
    QMessageBox.critical = _no_modal  # type: ignore[assignment]
    login_dialog_module.flush_pending_media_uploads = lambda: 0

    dialog = None
    window = None
    try:
        dialog = LoginDialog()
        dialog._base_url.setText(base_url)  # noqa: SLF001
        dialog._username.setText(username)  # noqa: SLF001
        dialog._password.setText(password)  # noqa: SLF001
        dialog._attempt_login()  # noqa: SLF001
        app.processEvents()

        if dialog.result() != int(QDialog.DialogCode.Accepted):
            raise RuntimeError(
                f"Login dialog did not accept credentials. status='{dialog._status.text()}'"  # noqa: SLF001
            )

        window = MainWindow()
        app.processEvents()
        if not window.windowTitle():
            raise RuntimeError("MainWindow initialized without a valid title.")
    finally:
        if window is not None:
            window.close()
        if dialog is not None:
            dialog.close()
        app.processEvents()
        QMessageBox.warning = original_warning  # type: ignore[assignment]
        QMessageBox.information = original_information  # type: ignore[assignment]
        QMessageBox.critical = original_critical  # type: ignore[assignment]
        login_dialog_module.flush_pending_media_uploads = original_flush


def main() -> int:
    args = _parse_args()
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    base_url = f"http://{args.host}:{args.port}"

    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env.setdefault("IMMOAPP_API_BASE_URL", base_url)
    _load_bootstrap_secret_env(env)
    _configure_isolated_smoke_secrets(env)
    _normalize_host_runtime_env(env)
    for key in _HOST_OVERRIDE_KEYS:
        value = env.get(key)
        if value:
            os.environ[key] = value

    stdout_tmp = tempfile.NamedTemporaryFile(
        prefix="immo_live_smoke_server_", suffix=".out.log", delete=False
    )
    stderr_tmp = tempfile.NamedTemporaryFile(
        prefix="immo_live_smoke_server_", suffix=".err.log", delete=False
    )
    stdout_path = Path(stdout_tmp.name)
    stderr_path = Path(stderr_tmp.name)
    stdout_tmp.close()
    stderr_tmp.close()
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")

    server_cmd = [
        args.server_python,
        "-u",
        str(root / "server" / "manage.py"),
        "runserver",
        f"{args.host}:{args.port}",
        "--noreload",
    ]
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            server_cmd,
            cwd=str(root),
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )

        _wait_for_server(base_url, args.startup_timeout_sec, args.request_timeout_sec)
        token: str | None = None
        first_auth_error: Exception | None = None
        try:
            token = _assert_api_login(
                base_url, args.username, args.password, args.request_timeout_sec
            )
        except Exception as exc:
            first_auth_error = exc

        if token is None:
            if not args.seed:
                raise RuntimeError(f"Auth failed and --no-seed was used: {first_auth_error}")
            _seed_admin(args.server_python, env, root)
            token = _assert_api_login(
                base_url, args.username, args.password, args.request_timeout_sec
            )

        _assert_client_login_and_main_window(base_url, args.username, args.password)
        print("[live-auth-smoke] PASS")
        return 0
    except Exception as exc:
        print(f"[live-auth-smoke] FAIL: {exc}", file=sys.stderr)
        print("[live-auth-smoke] server stderr tail:", file=sys.stderr)
        print(_tail(stderr_path), file=sys.stderr)
        print("[live-auth-smoke] server stdout tail:", file=sys.stderr)
        print(_tail(stdout_path), file=sys.stderr)
        return 1
    finally:
        if process is not None:
            _terminate_process(process)
        stdout_handle.close()
        stderr_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
