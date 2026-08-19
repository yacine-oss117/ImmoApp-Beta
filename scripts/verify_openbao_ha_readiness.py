from __future__ import annotations

import os
import urllib.error
import urllib.request


def _is_truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _in_production() -> bool:
    env = (os.environ.get("IMMOAPP_ENV") or "").strip().lower()
    if env in {"prod", "production"}:
        return True
    if env in {"dev", "development", "local", "test", "ci"}:
        return False
    return not _is_truthy(os.environ.get("DJANGO_DEBUG"))


def _bao_addrs() -> list[str]:
    raw = (os.environ.get("BAO_ADDRS") or "").strip()
    if raw:
        addrs = [a.strip().rstrip("/") for a in raw.split(",") if a.strip()]
        if addrs:
            return addrs
    single = (os.environ.get("BAO_ADDR") or "http://openbao:8200").strip().rstrip("/")
    return [single] if single else []


def _check_health(addr: str, timeout: float) -> tuple[bool, str]:
    url = f"{addr}/v1/sys/health?standbyok=true&perfstandbyok=true"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            code = int(response.status)
            return (code in {200, 429, 472, 473}, f"status={code}")
    except urllib.error.HTTPError as exc:
        code = int(exc.code)
        return (code in {200, 429, 472, 473}, f"status={code}")
    except Exception as exc:
        return (False, str(exc))


def main() -> None:
    backend = (os.environ.get("IMMOAPP_SECRETS_BACKEND") or "openbao").strip().lower()
    enforce = _is_truthy(os.environ.get("IMMOAPP_ENFORCE_OPENBAO_HA")) or _in_production()
    timeout = float(os.environ.get("BAO_TIMEOUT", "5"))

    if backend != "openbao":
        print("verify_openbao_ha_readiness: skipped (non-openbao backend)")
        return

    addrs = _bao_addrs()
    if not addrs:
        raise SystemExit("verify_openbao_ha_readiness: no OpenBao address configured")
    if enforce and len(addrs) < 2:
        raise SystemExit(
            "verify_openbao_ha_readiness: production/enforced mode requires BAO_ADDRS with >=2 nodes"
        )

    failures: list[str] = []
    ok_count = 0
    for addr in addrs:
        ok, detail = _check_health(addr, timeout)
        if ok:
            ok_count += 1
        else:
            failures.append(f"{addr}: {detail}")

    if enforce and ok_count == 0:
        raise SystemExit(
            "verify_openbao_ha_readiness: no healthy OpenBao endpoints. " + "; ".join(failures)
        )
    if not enforce and ok_count == 0:
        print(
            "verify_openbao_ha_readiness: warning (no healthy endpoint detected): "
            + "; ".join(failures)
        )
        return

    print(
        "verify_openbao_ha_readiness: OK "
        f"(healthy={ok_count}/{len(addrs)} enforce={str(enforce).lower()})"
    )


if __name__ == "__main__":
    main()
