from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_BASE_ENDPOINTS: dict[str, str] = {
    "signoz_ui": "http://127.0.0.1:3301",
    "otel_http": "http://127.0.0.1:4318/v1/traces",
}


def _probe(url: str, *, method: str = "GET") -> tuple[bool, str]:
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return True, f"http {int(resp.status)}"
    except urllib.error.HTTPError as exc:
        return True, f"http {int(exc.code)}"
    except Exception as exc:
        return False, str(exc)


def main() -> None:
    endpoints = dict(_BASE_ENDPOINTS)
    query_url = os.environ.get("SIGNOZ_QUERY_HEALTH_URL", "").strip()
    if query_url:
        endpoints["query_service"] = query_url

    results: dict[str, dict[str, str | bool]] = {}
    ok_all = True

    for name, url in endpoints.items():
        method = "POST" if name == "otel_http" else "GET"
        ok, detail = _probe(url, method=method)
        results[name] = {"ok": ok, "detail": detail, "url": url}
        ok_all = ok_all and ok

    print(json.dumps(results, indent=2))
    if not ok_all:
        raise SystemExit("verify_observability_stack: one or more endpoints are unreachable")
    print("verify_observability_stack: OK")


if __name__ == "__main__":
    main()
