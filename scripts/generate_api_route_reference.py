from __future__ import annotations

import os
import sys
from collections import defaultdict
import inspect
from pathlib import Path
from typing import TYPE_CHECKING

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("IMMOAPP_SECRETS_BACKEND", "env")
os.environ.setdefault("IMMOAPP_ALLOW_ENV_SECRETS", "1")
os.environ.setdefault("IMMOAPP_SECRETS_REQUIRED", "0")
os.environ.setdefault("IMMOAPP_SECRETS_OVERWRITE", "0")
os.environ.setdefault("IMMOAPP_SKIP_CELERY_APP", "1")
os.environ.setdefault("IMMOAPP_ALLOW_HTTP_ONLY_ASGI_FALLBACK", "1")
os.environ.setdefault("DJANGO_SECRET_KEY", "docs-route-reference-unsafe-for-prod")
os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
os.environ.setdefault("POSTGRES_HOST", "127.0.0.1")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "immoapp")
os.environ.setdefault("POSTGRES_USER", "immoapp_app")
os.environ.setdefault("POSTGRES_PASSWORD", "immoapp_app_password")
os.environ.setdefault("POSTGRES_ADMIN_USER", "immoapp")
os.environ.setdefault("POSTGRES_ADMIN_PASSWORD", "immoapp_admin_password")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")

import django

django.setup()

from django.urls.resolvers import URLPattern, URLResolver

from repo_layout import DOCS_REFERENCE_ROOT
from server.api.route_registry import iter_registered_routes
from server.immoapp_server.urls import urlpatterns as root_urlpatterns

if TYPE_CHECKING:
    from server.api.route_registry import RouteSpec

OUTPUT_PATH = DOCS_REFERENCE_ROOT / "API_ROUTE_REFERENCE.md"


def _methods_for_callback(callback: object) -> str:
    unwrapped = inspect.unwrap(callback)
    cls = getattr(unwrapped, "cls", None) or getattr(callback, "cls", None)
    if cls is not None:
        try:
            instance = cls()
            instance_methods = getattr(instance, "allowed_methods", None)
            if isinstance(instance_methods, (list, tuple)):
                filtered = [
                    str(item).upper()
                    for item in instance_methods
                    if str(item).strip() and str(item).upper() not in {"HEAD", "OPTIONS"}
                ]
                if filtered:
                    return ", ".join(sorted(set(filtered)))
        except Exception:
            pass

    methods = getattr(callback, "allowed_methods", None)
    values: list[str] = []
    if isinstance(methods, (list, tuple)):
        values.extend(str(item).upper() for item in methods if str(item).strip())
    cls = getattr(callback, "cls", None)
    if cls is not None:
        class_methods = getattr(cls, "http_method_names", None)
        if isinstance(class_methods, (list, tuple)):
            values.extend(str(item).upper() for item in class_methods if str(item).strip())
    if not values:
        return "GET"
    filtered = [item for item in values if item not in {"HEAD", "OPTIONS"}]
    final = filtered or list(dict.fromkeys(values))
    return ", ".join(sorted(set(final)))


def _callback_label(callback: object) -> str:
    unwrapped = inspect.unwrap(callback)
    cls = getattr(unwrapped, "cls", None) or getattr(callback, "cls", None)
    if cls is not None:
        return f"{cls.__module__}.{cls.__name__}"
    module = getattr(unwrapped, "__module__", getattr(callback, "__module__", ""))
    name = getattr(
        unwrapped, "__name__", getattr(callback, "__name__", callback.__class__.__name__)
    )
    return f"{module}.{name}".strip(".")


def _group_key(route_path: str) -> str:
    normalized = route_path.strip("/")
    if not normalized:
        return "root"
    return normalized.split("/", 1)[0]


def _render_root_routes() -> list[str]:
    lines = [
        "## Root routes",
        "",
        "| Path | Methods | View |",
        "| --- | --- | --- |",
    ]
    for pattern in root_urlpatterns:
        if isinstance(pattern, URLResolver):
            route = str(pattern.pattern)
            if route.startswith("admin/"):
                target = "django.contrib.admin.site.urls"
            elif route.startswith("api/v1/"):
                target = "server.api.urls"
            else:
                target = getattr(pattern.urlconf_name, "__name__", None) or str(
                    pattern.urlconf_name
                )
            lines.append(f"| `/{route}` | include | `{target}` |")
            continue
        if not isinstance(pattern, URLPattern):
            continue
        route = str(pattern.pattern)
        methods = _methods_for_callback(pattern.callback)
        view_name = _callback_label(pattern.callback)
        lines.append(f"| `/{route}` | `{methods}` | `{view_name}` |")
    return lines


def _render_group(name: str, specs: list["RouteSpec"]) -> list[str]:
    lines = [
        f"### {name}",
        "",
        "| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for spec in specs:
        methods = _methods_for_callback(spec.view)
        view_name = _callback_label(spec.view)
        policy = spec.policy
        lines.append(
            "| "
            + f"`/api/v1/{spec.path}` | "
            + f"`{methods}` | "
            + f"`{view_name}` | "
            + f"`{policy.policy_id}` | "
            + f"`{policy.retry_class}` | "
            + f"`{policy.cost_class}` | "
            + f"`{policy.replay_mode}` | "
            + ("yes" if policy.sla_facing else "no")
            + " |"
        )
    return lines


def render_api_route_reference() -> str:
    specs = list(iter_registered_routes())
    grouped: dict[str, list[RouteSpec]] = defaultdict(list)
    for spec in specs:
        grouped[_group_key(spec.path)].append(spec)

    lines = [
        "# API Route Reference",
        "",
        "Generated from the live Django URL config and the declarative `/api/v1/` route registry.",
        "Do not hand-edit this file. Rebuild it with `python scripts/generate_api_route_reference.py`.",
        "",
        f"- root routes: {len(root_urlpatterns)} top-level entries",
        f"- `/api/v1/` routes: {len(specs)} registered endpoints",
        "",
        "Use this file when you need the exact current route surface. Use",
        "`API_VERSIONING_PAGINATION_POLICY.md` for contract rules and budgets.",
        "",
    ]
    lines.extend(_render_root_routes())
    lines.extend(["", "## `/api/v1/` routes", ""])
    for group_name in sorted(grouped):
        lines.extend(_render_group(group_name, grouped[group_name]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    OUTPUT_PATH.write_text(render_api_route_reference(), encoding="utf-8")
    print(f"generate_api_route_reference: wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
