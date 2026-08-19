"""Security/compliance API client helpers for desktop UX flows."""

from __future__ import annotations

from typing import cast

from app.services.api_client import api_get, api_post, as_dict

_STEP_UP_HEADER = "X-Immoapp-Step-Up"


def step_up_auth(*, password: str, mfa_code: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"password": password}
    if mfa_code:
        payload["mfa_code"] = mfa_code
    response = as_dict(api_post("/auth/step-up/", payload, headers={}))
    return cast(dict[str, object], response)


def get_mfa_status() -> dict[str, object]:
    return cast(dict[str, object], as_dict(api_get("/auth/mfa/totp/")))


def start_mfa_enrollment(*, step_up_token: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        as_dict(
            api_post("/auth/mfa/totp/enroll/start/", {}, headers={_STEP_UP_HEADER: step_up_token})
        ),
    )


def confirm_mfa_enrollment(*, code: str, step_up_token: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        as_dict(
            api_post(
                "/auth/mfa/totp/enroll/confirm/",
                {"code": code},
                headers={_STEP_UP_HEADER: step_up_token},
            )
        ),
    )


def disable_mfa(*, code: str, step_up_token: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        as_dict(
            api_post(
                "/auth/mfa/totp/disable/",
                {"code": code},
                headers={_STEP_UP_HEADER: step_up_token},
            )
        ),
    )


def list_sessions() -> list[dict[str, object]]:
    payload = as_dict(api_get("/auth/sessions/"))
    items = payload.get("items")
    if isinstance(items, list):
        return cast(list[dict[str, object]], items)
    return []


def revoke_session(*, session_id: str, step_up_token: str) -> None:
    api_post(
        f"/auth/sessions/{session_id}/revoke/",
        {},
        headers={_STEP_UP_HEADER: step_up_token},
    )


def revoke_all_sessions(*, keep_current: bool, step_up_token: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        as_dict(
            api_post(
                "/auth/sessions/revoke-all/",
                {"keep_current": bool(keep_current)},
                headers={_STEP_UP_HEADER: step_up_token},
            )
        ),
    )


def permissions_matrix() -> list[dict[str, object]]:
    payload = as_dict(api_get("/users/permissions/matrix/"))
    items = payload.get("items")
    if isinstance(items, list):
        return cast(list[dict[str, object]], items)
    return []


def list_permission_grants(*, status: str | None = None) -> list[dict[str, object]]:
    params: dict[str, str] = {}
    if status:
        params["status"] = status
    payload = as_dict(api_get("/users/permissions/grants/", params=params))
    items = payload.get("items")
    if isinstance(items, list):
        return cast(list[dict[str, object]], items)
    return []


def request_permission_grant(
    *,
    user_id: int,
    permission: str,
    reason: str,
    step_up_token: str,
) -> dict[str, object]:
    return cast(
        dict[str, object],
        as_dict(
            api_post(
                "/users/permissions/grants/",
                {"user_id": int(user_id), "permission": permission, "reason": reason},
                headers={_STEP_UP_HEADER: step_up_token},
            )
        ),
    )


def approve_permission_grant(
    *,
    request_id: int,
    reason: str,
    duration_minutes: int,
    step_up_token: str,
) -> dict[str, object]:
    return cast(
        dict[str, object],
        as_dict(
            api_post(
                f"/users/permissions/grants/{int(request_id)}/approve/",
                {"reason": reason, "duration_minutes": int(duration_minutes)},
                headers={_STEP_UP_HEADER: step_up_token},
            )
        ),
    )


def deny_permission_grant(*, request_id: int, reason: str, step_up_token: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        as_dict(
            api_post(
                f"/users/permissions/grants/{int(request_id)}/deny/",
                {"reason": reason},
                headers={_STEP_UP_HEADER: step_up_token},
            )
        ),
    )


def revoke_permission_grant(
    *, request_id: int, reason: str, step_up_token: str
) -> dict[str, object]:
    return cast(
        dict[str, object],
        as_dict(
            api_post(
                f"/users/permissions/grants/{int(request_id)}/revoke/",
                {"reason": reason},
                headers={_STEP_UP_HEADER: step_up_token},
            )
        ),
    )


def create_compliance_export(
    *,
    user_id: int,
    reason: str,
    step_up_token: str,
) -> dict[str, object]:
    return cast(
        dict[str, object],
        as_dict(
            api_post(
                f"/compliance/users/{int(user_id)}/export/",
                {"reason": reason},
                headers={_STEP_UP_HEADER: step_up_token},
            )
        ),
    )


def create_compliance_delete(
    *,
    user_id: int,
    reason: str,
    step_up_token: str,
) -> dict[str, object]:
    return cast(
        dict[str, object],
        as_dict(
            api_post(
                f"/compliance/users/{int(user_id)}/delete/",
                {"reason": reason},
                headers={_STEP_UP_HEADER: step_up_token},
            )
        ),
    )


def get_compliance_job(*, job_id: str) -> dict[str, object]:
    return cast(dict[str, object], as_dict(api_get(f"/compliance/jobs/{job_id}/")))


def download_compliance_export(*, job_id: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        as_dict(api_get(f"/compliance/exports/{job_id}/download/")),
    )


__all__ = [
    "approve_permission_grant",
    "confirm_mfa_enrollment",
    "create_compliance_delete",
    "create_compliance_export",
    "deny_permission_grant",
    "disable_mfa",
    "download_compliance_export",
    "get_compliance_job",
    "get_mfa_status",
    "list_permission_grants",
    "list_sessions",
    "permissions_matrix",
    "request_permission_grant",
    "revoke_all_sessions",
    "revoke_permission_grant",
    "revoke_session",
    "start_mfa_enrollment",
    "step_up_auth",
]
