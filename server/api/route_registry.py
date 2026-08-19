"""Declarative API route registry for automatic URL pattern generation."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

from django.http import HttpResponseBase
from django.urls import URLPattern, path

from core.contracts.http_policy import RoutePolicy, policy_to_dict
from core.contracts.route_policy_registry import get_explicit_route_policy

_VIEWS_GLOB = "views_*.py"


RouteView = TypeVar("RouteView", bound=Callable[..., object])


@dataclass(frozen=True)
class RouteSpec:
    path: str
    view: Callable[..., object]
    order: int
    name: str | None
    policy: RoutePolicy


_ROUTES_BY_PATH: dict[str, RouteSpec] = {}
_MODULES_LOADED = False
_POLICY_UNSET = object()


def route(
    route_path: str,
    *,
    order: int | None = None,
    name: str | None = None,
    policy: RoutePolicy | object = _POLICY_UNSET,
) -> Callable[[RouteView], RouteView]:
    """Register an API route for a view function."""

    normalized = route_path.strip()
    if not normalized:
        raise ValueError("route_path must not be empty")
    if normalized.startswith("/"):
        raise ValueError("route_path must be relative (without leading slash)")

    def _decorator(view: RouteView) -> RouteView:
        existing = _ROUTES_BY_PATH.get(normalized)
        if existing is not None:
            if existing.view is not view:
                raise RuntimeError(
                    f"Duplicate API route path '{normalized}' for "
                    f"{existing.view.__module__}.{existing.view.__name__} and "
                    f"{view.__module__}.{view.__name__}"
                )
            return view

        resolved_order = order if order is not None else len(_ROUTES_BY_PATH)
        if policy is _POLICY_UNSET:
            resolved_policy = get_explicit_route_policy(normalized)
            if resolved_policy is None:
                raise RuntimeError(
                    "Missing explicit route policy for "
                    f"'{normalized}'. Add it to core/contracts/route_policy_registry.py."
                )
        elif isinstance(policy, RoutePolicy):
            resolved_policy = policy
        else:
            raise RuntimeError(
                f"Invalid route policy for '{normalized}'. Pass a RoutePolicy instance."
            )
        cast_view = view
        cast(Any, cast_view)._immo_route_path = normalized
        cast(Any, cast_view)._immo_route_policy_id = resolved_policy.policy_id
        _ROUTES_BY_PATH[normalized] = RouteSpec(
            path=normalized,
            view=cast_view,
            order=resolved_order,
            name=name,
            policy=resolved_policy,
        )
        return cast_view

    return _decorator


def _extract_http_methods(view: Callable[..., object]) -> tuple[str, ...]:
    methods = getattr(view, "allowed_methods", None)
    if isinstance(methods, (list, tuple)):
        values = [str(m).upper() for m in methods if str(m).strip()]
        if values:
            return tuple(sorted(set(values)))
    cls = getattr(view, "cls", None)
    if cls is not None:
        names = getattr(cls, "http_method_names", None)
        if isinstance(names, (list, tuple)):
            values = [str(name).upper() for name in names if str(name).strip()]
            if values:
                return tuple(sorted(set(values)))
    return ("GET",)


def _load_route_modules() -> None:
    global _MODULES_LOADED
    if _MODULES_LOADED:
        return

    api_dir = Path(__file__).resolve().parent
    module_names = sorted(p.stem for p in api_dir.glob(_VIEWS_GLOB))
    for module_name in module_names:
        importlib.import_module(f"server.api.{module_name}")
    _MODULES_LOADED = True


def iter_registered_routes() -> tuple[RouteSpec, ...]:
    _load_route_modules()
    return tuple(sorted(_ROUTES_BY_PATH.values(), key=lambda spec: (spec.order, spec.path)))


def build_urlpatterns() -> list[URLPattern]:
    """Build Django URL patterns from the registered route specs."""

    specs = iter_registered_routes()
    patterns: list[URLPattern] = []
    for spec in specs:
        if spec.name is None:
            patterns.append(path(spec.path, cast(Callable[..., HttpResponseBase], spec.view)))
        else:
            patterns.append(
                path(spec.path, cast(Callable[..., HttpResponseBase], spec.view), name=spec.name)
            )
    return patterns


def resolve_route_template(route: str | None, *, request_path: str | None = None) -> str:
    if route:
        normalized = route.strip().lstrip("/")
        if normalized.startswith("api/v1/"):
            normalized = normalized[7:]
        if normalized in _ROUTES_BY_PATH:
            return normalized
    if request_path:
        candidate = request_path.strip().lstrip("/")
        if candidate.startswith("api/v1/"):
            candidate = candidate[7:]
        if candidate in _ROUTES_BY_PATH:
            return candidate
    return (route or request_path or "").strip().lstrip("/")


def route_policy_manifest() -> dict[str, dict[str, object]]:
    manifest: dict[str, dict[str, object]] = {}
    for spec in iter_registered_routes():
        manifest[spec.path] = policy_to_dict(spec.policy)
    return manifest


def get_route_policy(route_path: str) -> RoutePolicy | None:
    _load_route_modules()
    spec = _ROUTES_BY_PATH.get(route_path)
    return spec.policy if spec is not None else None


def reset_registry_for_tests() -> None:
    """Reset global state for isolated tests."""
    global _MODULES_LOADED
    _ROUTES_BY_PATH.clear()
    _MODULES_LOADED = False


__all__ = [
    "RouteSpec",
    "build_urlpatterns",
    "get_route_policy",
    "iter_registered_routes",
    "resolve_route_template",
    "route_policy_manifest",
    "reset_registry_for_tests",
    "route",
]
