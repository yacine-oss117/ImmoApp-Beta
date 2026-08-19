"""
Runtime OpenAPI smoke test.

Ensures the generated schema includes critical sync endpoints.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _build_schema() -> dict[str, object]:
    repo_root = Path(__file__).parents[3]
    server_dir = repo_root / "server"
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django

    django.setup()
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    if hasattr(schema, "to_dict"):
        return schema.to_dict()  # type: ignore[no-any-return]
    return schema  # type: ignore[return-value]


def test_openapi_schema_includes_sync_paths() -> None:
    schema = _build_schema()
    paths = schema.get("paths", {}) if isinstance(schema, dict) else {}
    expected = [
        "/api/v1/clients/changes/",
        "/api/v1/listings/changes/",
        "/api/v1/demandes/changes/",
        "/api/v1/offers/changes/",
        "/api/v1/offers/photos/changes/",
        "/api/v1/crm/visits/changes/",
        "/api/v1/crm/contracts/changes/",
        "/api/v1/crm/articles/changes/",
        "/api/v1/locations/changes/",
        "/api/v1/templates/changes/",
        "/api/v1/settings/agency/changes/",
    ]
    missing = [path for path in expected if path not in paths]
    assert not missing, f"OpenAPI schema missing paths: {missing}"


def test_openapi_sync_paths_have_get() -> None:
    schema = _build_schema()
    paths = schema.get("paths", {}) if isinstance(schema, dict) else {}
    expected = [
        "/api/v1/clients/changes/",
        "/api/v1/listings/changes/",
        "/api/v1/demandes/changes/",
        "/api/v1/offers/changes/",
        "/api/v1/offers/photos/changes/",
        "/api/v1/crm/visits/changes/",
        "/api/v1/crm/contracts/changes/",
        "/api/v1/crm/articles/changes/",
        "/api/v1/locations/changes/",
        "/api/v1/templates/changes/",
        "/api/v1/settings/agency/changes/",
    ]
    missing = [path for path in expected if "get" not in paths.get(path, {})]
    assert not missing, f"OpenAPI schema missing GET ops for: {missing}"
