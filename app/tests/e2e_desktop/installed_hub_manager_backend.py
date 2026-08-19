from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import requests

_MANAGED_DISTRO = "ImmoAppRuntime"
_MANAGED_WEB_CONTAINER = "immoapp-managed-hub-web-1"
_APPROVAL_URL_RE = re.compile(r"Approve:\s*(?P<url>https?://\S+/api/v1/auth/register/approve/\S+/)")
_ACTIVATION_CODE_RE = re.compile(r"Activation code:\s*(?P<code>[A-Z0-9]{8})")


@dataclass(frozen=True)
class ManagedOwner:
    email: str
    password: str
    agency_name: str

    @property
    def username(self) -> str:
        return self.email


def managed_front_door_url() -> str:
    return str(
        os.environ.get("IMMOAPP_E2E_MANAGED_FRONT_DOOR_URL", "http://127.0.0.1:18001")
    ).rstrip("/")


def platform_admin_email() -> str:
    value = str(os.environ.get("IMMOAPP_E2E_MANAGED_PLATFORM_ADMIN_EMAIL", "")).strip()
    if not value:
        raise AssertionError("IMMOAPP_E2E_MANAGED_PLATFORM_ADMIN_EMAIL is required.")
    return value


def wait_for_front_door(*, ready: bool, timeout: float = 360.0) -> None:
    url = f"{managed_front_door_url()}/api/v1/health/"
    deadline = time.monotonic() + timeout
    last_status = 0
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = requests.get(url, timeout=3.0)
            last_status = int(response.status_code)
            if ready and response.status_code == 200:
                return
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if not ready:
                return
        time.sleep(0.5)
    expected = "ready" if ready else "stopped"
    raise AssertionError(
        f"Managed Hub front door did not become {expected}: status={last_status} "
        f"error={last_error}"
    )


def ensure_managed_hub_running() -> None:
    health_url = f"{managed_front_door_url()}/api/v1/health/"
    try:
        response = requests.get(health_url, timeout=3.0)
        if response.status_code == 200:
            return
    except requests.RequestException:
        pass

    installed_exe = str(os.environ.get("IMMOAPP_E2E_INSTALLED_HUB_MANAGER_PATH", "") or "").strip()
    if not installed_exe:
        raise AssertionError("Installed Hub Manager path is required for managed cleanup.")
    script = Path(installed_exe).resolve().parent / "scripts" / "hub_manager.ps1"
    if not script.is_file():
        raise AssertionError(f"Installed Hub Manager authority is missing: {script}")
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Action",
            "start",
            "-HubBaseUrl",
            managed_front_door_url(),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            "Managed Hub recovery start failed before E2E owner cleanup: "
            f"exit={result.returncode}\n{result.stderr}"
        )
    wait_for_front_door(ready=True)


def _run_managed_django(code: str, *, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "wsl.exe",
            "-d",
            _MANAGED_DISTRO,
            "--",
            "docker",
            "exec",
            _MANAGED_WEB_CONTAINER,
            "python",
            "server/manage.py",
            "shell",
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _managed_django_json(code: str, *, timeout: int = 90) -> Any:
    result = _run_managed_django(code, timeout=timeout)
    if result.returncode != 0:
        raise AssertionError(
            "Managed Django observer failed without exposing command arguments: "
            f"exit={result.returncode}\n{result.stderr}"
        )
    for line in reversed(result.stdout.splitlines()):
        candidate = line.strip()
        if not candidate or candidate[0] not in "[{":
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise AssertionError("Managed Django observer did not return JSON.")


def suspend_active_hub_owners_and_admins() -> list[tuple[int, bool]]:
    payload = _managed_django_json(
        "import json; from django.db.models import Q; "
        "from server.accounts.models import User; "
        "q=Q(is_superuser=True)|Q(role='manager',is_owner=True)|"
        "Q(role='manager',can_hard_delete=True); "
        "rows=list(User.objects.filter(is_active=True).filter(q).values_list('id','is_active')); "
        "User.objects.filter(id__in=[r[0] for r in rows]).update(is_active=False); "
        "print(json.dumps(rows))"
    )
    assert isinstance(payload, list)
    return [(int(row[0]), bool(row[1])) for row in payload]


def restore_hub_owner_admin_activity(snapshot: list[tuple[int, bool]]) -> None:
    if not snapshot:
        return
    literal = repr([(int(user_id), bool(active)) for user_id, active in snapshot])
    _managed_django_json(
        "import json; from server.accounts.models import User; "
        f"rows={literal}; "
        "[User.objects.filter(id=i).update(is_active=a) for i,a in rows]; "
        "print(json.dumps({'restored':len(rows)}))"
    )


def managed_user_by_email(email: str) -> dict[str, Any] | None:
    email_literal = repr(str(email))
    payload = _managed_django_json(
        "import json; from django.db.models import Q; "
        "from server.accounts.models import User; "
        f"email={email_literal}; "
        "row=User.objects.filter(Q(email__iexact=email)|Q(username__iexact=email))."
        "values('id','agency_id','username','email','role','is_owner','is_active').first(); "
        "print(json.dumps(row))"
    )
    if payload is None:
        return None
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


def latest_email(
    *,
    to_email: str,
    subject_contains: str = "",
    body_contains: str = "",
) -> dict[str, str] | None:
    to_literal = repr(str(to_email))
    subject_literal = repr(str(subject_contains))
    body_literal = repr(str(body_contains))
    payload = _managed_django_json(
        "import json; from server.accounts.models import EmailOutbox; "
        f"to_email={to_literal}; subject_part={subject_literal}; body_part={body_literal}; "
        "q=EmailOutbox.objects.filter(to_email__iexact=to_email); "
        "q=q.filter(subject__icontains=subject_part) if subject_part else q; "
        "q=q.filter(body_text__icontains=body_part) if body_part else q; "
        "row=q.order_by('-created_at').values('id','to_email','subject','body_text').first(); "
        "print(json.dumps(row,default=str))"
    )
    if payload is None:
        return None
    assert isinstance(payload, dict)
    return {str(key): str(value) for key, value in payload.items()}


def wait_for_email(
    *,
    to_email: str,
    subject_contains: str = "",
    body_contains: str = "",
    timeout: float = 60.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = latest_email(
            to_email=to_email,
            subject_contains=subject_contains,
            body_contains=body_contains,
        )
        if row is not None:
            return row
        time.sleep(0.5)
    raise AssertionError(
        f"Managed email was not queued for {to_email!r} with expected subject/body."
    )


def cleanup_owner_registration(owner_email: str, *, admin_email: str = "") -> None:
    email_literal = repr(str(owner_email).strip().lower())
    admin_literal = repr(str(admin_email).strip().lower())
    _managed_django_json(
        "import json; from django.db.models import Q; "
        "from server.accounts.models import Agency,EmailOutbox,RegistrationRequest,User; "
        f"email={email_literal}; admin_email={admin_literal}; "
        "user=User.objects.filter(Q(email__iexact=email)|Q(username__iexact=email)).first(); "
        "agency_id=user.agency_id if user else None; "
        "user.delete() if user else None; "
        "Agency.objects.filter(id=agency_id).delete() if agency_id else None; "
        "RegistrationRequest.objects.filter(owner_email__iexact=email).delete(); "
        "EmailOutbox.objects.filter(Q(to_email__iexact=email)|Q(body_text__icontains=email)|"
        "Q(body_html__icontains=email)).delete(); "
        "EmailOutbox.objects.filter(to_email__iexact=admin_email,body_text__icontains=email)."
        "delete() if admin_email else None; "
        "print(json.dumps({'cleaned':True}))"
    )


def cleanup_managed_e2e_owner_records() -> None:
    _managed_django_json(
        "import json; from django.db.models import Q; "
        "from server.accounts.models import EmailOutbox,RegistrationRequest,User; "
        "prefix_a='installed-hub-owner-'; prefix_b='installed-first-owner-'; "
        "user_q=Q(email__startswith=prefix_a)|Q(username__startswith=prefix_a)|"
        "Q(email__startswith=prefix_b)|Q(username__startswith=prefix_b); "
        "request_q=Q(owner_email__startswith=prefix_a)|"
        "Q(owner_email__startswith=prefix_b); "
        "email_q=Q(to_email__startswith=prefix_a)|Q(to_email__startswith=prefix_b)|"
        "Q(body_text__contains=prefix_a)|Q(body_text__contains=prefix_b)|"
        "Q(body_html__contains=prefix_a)|Q(body_html__contains=prefix_b); "
        "users=User.objects.filter(user_q).count(); "
        "requests=RegistrationRequest.objects.filter(request_q).count(); "
        "emails=EmailOutbox.objects.filter(email_q).count(); "
        "User.objects.filter(user_q).delete(); "
        "RegistrationRequest.objects.filter(request_q).delete(); "
        "EmailOutbox.objects.filter(email_q).delete(); "
        "print(json.dumps({'users':users,'requests':requests,'emails':emails}))"
    )


def _extract(
    pattern: re.Pattern[str],
    body: str,
    *,
    group: str,
    label: str,
) -> str:
    match = pattern.search(body)
    if match is None:
        raise AssertionError(f"Managed lifecycle email did not contain {label}.")
    return match.group(group)


def extract_approval_url(body: str) -> str:
    return _extract(_APPROVAL_URL_RE, body, group="url", label="approval URL")


def extract_activation_code(body: str) -> str:
    return _extract(
        _ACTIVATION_CODE_RE,
        body,
        group="code",
        label="activation code",
    )


def provision_active_owner() -> ManagedOwner:
    suffix = uuid.uuid4().hex[:10]
    owner = ManagedOwner(
        email=f"installed-hub-owner-{suffix}@example.test",
        password="InstalledOwnerStrongPass_123!",
        agency_name=f"Installed Hub Agency {suffix}",
    )
    admin_email = platform_admin_email()
    cleanup_managed_e2e_owner_records()
    cleanup_owner_registration(owner.email, admin_email=admin_email)
    response = requests.post(
        f"{managed_front_door_url()}/api/v1/auth/register/",
        json={
            "agency_name": owner.agency_name,
            "legal_name": f"{owner.agency_name} SARL",
            "registry_number": f"RC-{suffix}",
            "agency_address": "12 Rue Didouche Mourad",
            "agency_city": "Algiers",
            "agency_postal_code": "16000",
            "owner_first_name": "Installed",
            "owner_last_name": "Owner",
            "owner_email": owner.email,
            "owner_phone": f"+213555{uuid.uuid4().int % 1_000_000:06d}",
            "terms_accepted": True,
        },
        timeout=15.0,
    )
    assert response.status_code == 200, response.text

    review_email = wait_for_email(
        to_email=admin_email,
        subject_contains="registration review",
        body_contains=owner.email,
    )
    approval_url = extract_approval_url(review_email["body_text"])
    approval = requests.post(approval_url, timeout=15.0)
    assert approval.status_code == 200

    activation_email = wait_for_email(
        to_email=owner.email,
        subject_contains="Welcome to ImmoApp",
        body_contains="Activation code:",
    )
    activation_code = extract_activation_code(activation_email["body_text"])
    activation = requests.post(
        f"{managed_front_door_url()}/api/v1/auth/activate/",
        json={
            "email": owner.email,
            "activation_code": activation_code,
            "password": owner.password,
            "password_confirm": owner.password,
        },
        timeout=15.0,
    )
    assert activation.status_code == 200, activation.text
    row = managed_user_by_email(owner.email)
    assert row is not None
    assert row["is_owner"] is True
    assert row["is_active"] is True
    return owner
